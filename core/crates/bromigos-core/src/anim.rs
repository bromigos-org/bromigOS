//! The live layer's animations: one switch per name, each setting one or more
//! `[section] key` booleans in the live config.

use serde::Serialize;
use thiserror::Error;

/// One switchable animation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Anim {
    pub name: &'static str,
    /// What it is, for listings.
    pub description: &'static str,
    /// The `(section, key)` booleans the switch sets; it is on when all are true.
    pub keys: &'static [(&'static str, &'static str)],
}

/// Every animation, in listing order.
pub const ANIMS: &[Anim] = &[
    a(
        "den",
        "the den's own screens made live (scope, burn-in monitor, meters, relay map)",
        &[("background", "den")],
    ),
    a(
        "streaks",
        "the left side's drifting glitch streaks",
        &[("loops", "streaks")],
    ),
    a(
        "rows",
        "the floor grid's rows scrolling toward you",
        &[("loops", "rows")],
    ),
    a(
        "rain",
        "glyph rain (density and speed follow CPU load)",
        &[("rain", "enabled")],
    ),
    a(
        "bursts",
        "rain columns flaring on notifications, alerts and fills",
        &[("rain", "bursts")],
    ),
    a(
        "pulses",
        "traffic pulses running the floor grid (follow network)",
        &[("floor", "enabled")],
    ),
    a(
        "sweep",
        "the X-ray scanner pass over this machine's schematic",
        &[("sweep", "enabled")],
    ),
    a("stars", "parallax star layers", &[("space", "stars")]),
    a(
        "ships",
        "ships and debris (density follows network traffic)",
        &[("space", "traffic")],
    ),
    a(
        "beam",
        "the station's beam while every lab node and service is up",
        &[("space", "relay_beam")],
    ),
    a(
        "tint",
        "amber/red lab-health tint on space and rain",
        &[("space", "health_tint")],
    ),
    a(
        "intercept",
        "the burn-in sequence at login and unlock",
        &[
            ("events", "intercept_on_login"),
            ("events", "intercept_on_unlock"),
        ],
    ),
    a(
        "flash",
        "the flash on critical notifications",
        &[("events", "critical_flash")],
    ),
    a(
        "wipe",
        "the wipe when switching workspaces",
        &[("events", "workspace_wipe")],
    ),
    a(
        "codec",
        "voiced codec calls for important events",
        &[("codec", "enabled")],
    ),
    a(
        "screensaver",
        "the idle screensaver",
        &[("screensaver", "enabled")],
    ),
    a(
        "sounds",
        "the live layer's sound cues",
        &[("sounds", "enabled")],
    ),
];

const fn a(
    name: &'static str,
    description: &'static str,
    keys: &'static [(&'static str, &'static str)],
) -> Anim {
    Anim {
        name,
        description,
        keys,
    }
}

/// Looks up one animation by name.
pub fn get(name: &str) -> Option<&'static Anim> {
    ANIMS.iter().find(|a| a.name == name)
}

/// Every name, in listing order.
pub fn names() -> Vec<&'static str> {
    ANIMS.iter().map(|a| a.name).collect()
}

#[derive(Debug, Error, PartialEq, Eq)]
pub enum NameError {
    #[error("name an animation (or 'all'); `bromigos anim` lists them")]
    Empty,
    #[error("unknown: {}. Known: {}, all", .0.join(", "), names().join(", "))]
    Unknown(Vec<String>),
}

/// Resolves names given on the command line: `all` anywhere means every animation;
/// otherwise each must be known (order kept, as given).
pub fn resolve<S: AsRef<str>>(args: &[S]) -> Result<Vec<&'static Anim>, NameError> {
    if args.is_empty() {
        return Err(NameError::Empty);
    }
    if args.iter().any(|s| s.as_ref() == "all") {
        return Ok(ANIMS.iter().collect());
    }
    let bad: Vec<String> = args
        .iter()
        .map(AsRef::as_ref)
        .filter(|n| get(n).is_none())
        .map(str::to_owned)
        .collect();
    if !bad.is_empty() {
        return Err(NameError::Unknown(bad));
    }
    Ok(args.iter().filter_map(|n| get(n.as_ref())).collect())
}

/// One `[section] key` an animation sets.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct KeyRef {
    pub section: &'static str,
    pub key: &'static str,
}

impl Anim {
    pub fn key_refs(&self) -> Vec<KeyRef> {
        self.keys
            .iter()
            .map(|(section, key)| KeyRef { section, key })
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn table_matches_the_python_cli() {
        assert_eq!(
            names(),
            [
                "den",
                "streaks",
                "rows",
                "rain",
                "bursts",
                "pulses",
                "sweep",
                "stars",
                "ships",
                "beam",
                "tint",
                "intercept",
                "flash",
                "wipe",
                "codec",
                "screensaver",
                "sounds"
            ]
        );
        assert_eq!(get("ships").unwrap().keys, &[("space", "traffic")]);
        assert_eq!(get("intercept").unwrap().keys.len(), 2);
        assert!(get("all").is_none());
    }

    #[test]
    fn resolve_names() {
        let r = resolve(&["rain", "ships"]).unwrap();
        assert_eq!(
            r.iter().map(|a| a.name).collect::<Vec<_>>(),
            ["rain", "ships"]
        );
        assert_eq!(resolve(&["rain", "all"]).unwrap().len(), ANIMS.len());
        assert_eq!(resolve::<&str>(&[]), Err(NameError::Empty));
        let e = resolve(&["rain", "snow", "Rain"]).unwrap_err();
        assert_eq!(e, NameError::Unknown(vec!["snow".into(), "Rain".into()]));
        assert!(
            e.to_string()
                .starts_with("unknown: snow, Rain. Known: den, streaks,")
        );
        assert!(e.to_string().ends_with("sounds, all"));
    }
}
