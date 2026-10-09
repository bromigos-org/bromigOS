//! `bromigos mute`: the desktop's one mute. The theme's sounds (the live layer's cues and
//! its codec calls, which honour the same switch) and VECTOR's voice go on and off
//! together. Each keeps its own state where it always has (the live layer's
//! `~/.local/state/bromigos-live/muted`, VECTOR's `vector-voice-muted`); this sets both
//! through their own commands, so a running daemon hears it at once and a stopped one
//! starts with it.

use std::path::Path;
use std::process::{Command, Stdio};

use anyhow::Result;
use bromigos_core::paths::Paths;
use clap::{Args, ValueEnum};
use serde_json::json;

use crate::SCHEMA;

#[derive(Clone, Copy, Debug, PartialEq, Eq, ValueEnum)]
pub enum Verb {
    /// Mute the theme's sounds and VECTOR's voice
    On,
    /// Unmute both
    Off,
    /// Anything unmuted: mute all; all muted: unmute all (the keys)
    Toggle,
    /// Say what is muted
    Status,
}

#[derive(Args, Debug)]
pub struct MuteArgs {
    #[arg(value_enum, default_value = "toggle")]
    verb: Verb,
    /// Print the JSON document
    #[arg(long)]
    json: bool,
}

/// One piece's mute through its own command (`<bin> mute on|off|status`): Some(muted),
/// or None when the piece isn't installed or didn't answer.
fn piece(bin: &Path, verb: &str) -> Option<bool> {
    let out = Command::new(bin)
        .args(["mute", verb])
        .stdin(Stdio::null())
        .stderr(Stdio::null())
        .output()
        .ok()?;
    match String::from_utf8_lossy(&out.stdout).trim() {
        "muted" => Some(true),
        "unmuted" => Some(false),
        _ => None,
    }
}

/// The state the desktop goes to: toggle mutes everything unless everything is muted.
pub fn target(verb: Verb, theme: Option<bool>, vector: Option<bool>) -> Option<bool> {
    match verb {
        Verb::On => Some(true),
        Verb::Off => Some(false),
        Verb::Status => None,
        Verb::Toggle => {
            let all = [theme, vector].iter().flatten().all(|m| *m);
            Some(!all)
        }
    }
}

pub fn mute_cmd(paths: &Paths, a: MuteArgs) -> Result<i32> {
    let (live, holo) = (paths.live_bin.as_path(), paths.holo_bin.as_path());
    let mut theme = piece(live, "status");
    let mut vector = piece(holo, "status");
    if let Some(on) = target(a.verb, theme, vector) {
        let v = if on { "on" } else { "off" };
        theme = piece(live, v);
        vector = piece(holo, v);
        let all = [theme, vector].iter().flatten().all(|m| *m == on);
        let what = match (on, all) {
            (true, true) => "ALL SOUND MUTED",
            (false, true) => "ALL SOUND UNMUTED",
            _ => "SOUND: NOT EVERYTHING ANSWERED",
        };
        let body = "The theme's sounds and VECTOR's voice (SUPER+SHIFT+M, SUPER+SHIFT+V)";
        // the bar's VECTOR pip shows the mute: refresh it now (its signal), not in 30 s
        let _ = Command::new("pkill")
            .args(["-RTMIN+9", "-x", "waybar"])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
        // the on-screen display (swayosd, bromigos-desktop) says it; a notification otherwise
        let icon = if on {
            "audio-volume-muted-symbolic"
        } else {
            "audio-volume-high-symbolic"
        };
        let osd = Command::new("swayosd-client")
            .args(["--custom-message", what, "--custom-icon", icon])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .is_ok_and(|s| s.success());
        if !osd {
            let _ = Command::new("notify-send")
                .args(["-a", "bromigos", "-u", "low", "-t", "1400", what, body])
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .status();
        }
    }
    let word = |m: Option<bool>| match m {
        Some(true) => "muted",
        Some(false) => "on",
        None => "not available",
    };
    let muted =
        [theme, vector].iter().flatten().all(|m| *m) && (theme.is_some() || vector.is_some());
    if a.json {
        println!(
            "{}",
            json!({"schema": SCHEMA, "muted": muted, "theme": theme, "vector": vector})
        );
    } else {
        println!(
            "{}  (theme sounds: {}; VECTOR's voice: {})",
            if muted { "muted" } else { "sound on" },
            word(theme),
            word(vector)
        );
    }
    Ok(if theme.is_none() && vector.is_none() {
        1
    } else {
        0
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn toggle_mutes_unless_everything_is_muted() {
        assert_eq!(target(Verb::Toggle, Some(false), Some(false)), Some(true));
        assert_eq!(target(Verb::Toggle, Some(true), Some(false)), Some(true)); // mixed: mute all
        assert_eq!(target(Verb::Toggle, Some(false), Some(true)), Some(true));
        assert_eq!(target(Verb::Toggle, Some(true), Some(true)), Some(false));
        assert_eq!(target(Verb::Toggle, Some(true), None), Some(false)); // no VECTOR: the theme alone
        assert_eq!(target(Verb::On, Some(true), Some(true)), Some(true));
        assert_eq!(target(Verb::Off, None, None), Some(false));
        assert_eq!(target(Verb::Status, Some(false), Some(true)), None);
    }
}
