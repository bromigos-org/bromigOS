//! XDG locations of everything the core reads or writes.
//!
//! All paths come from one [`Paths`] value built from the environment, so tests (and
//! packaged installs) can point the whole core somewhere else without touching the
//! process environment.
//!
//! Three homes, as in Omarchy: read-only defaults in `/usr/share/bromigos/`; what the
//! user deliberately owns (their switches, profile, themes, plugins) in
//! `~/.config/bromigos/`; generated state in `~/.local/state/bromigos/`.
//!
//! | Variable | Default |
//! |---|---|
//! | `XDG_RUNTIME_DIR` | `/run/user/<uid>` |
//! | `XDG_CONFIG_HOME` | `~/.config` |
//! | `XDG_STATE_HOME` | `~/.local/state` |
//! | `XDG_DATA_HOME` | `~/.local/share` (installed extensions: `bromigos ext`) |
//! | `XDG_CACHE_HOME` | `~/.cache` (the extension catalogs' copies) |
//! | `BROMIGOS_SHARE_DIR` | `/usr/share/bromigos` (read-only defaults) |
//! | `BROMIGOS_LIB_BIN` | `/usr/lib/bromigos/bin` (packaged `bromigos-<group>-<name>` commands) |
//! | `BROMIGOS_LIVE_CONFIG` | `$XDG_CONFIG_HOME/bromigos-live/config.toml` (the live layer honours it too) |
//! | `BROMIGOS_LIVE_BIN` | `/usr/bin/bromigos-live` (package `bromigos-live`) when installed, else `$XDG_CONFIG_HOME/bromigos-live/bin/bromigos-live` |
//! | `BROMIGOS_HOLO_BIN` | `/usr/bin/bromigos-holo` (package `bromigos-vector`) when installed, else `$XDG_CONFIG_HOME/bromigos/holo/bin/bromigos-holo` |
//! | `BROMIGOS_WALLPAPER_BIN` | `$XDG_CONFIG_HOME/bromigos/bin/bromigos-wallpaper` |
//! | `BROMIGOS_PACMAN_LOCAL` | `/var/lib/pacman/local` (pacman's database of installed packages, read by `bromigos update`) |

use std::path::{Path, PathBuf};

/// The packaged live layer's launcher (`bromigos-live`), preferred over the dotfiles' when present.
pub const LIVE_BIN_PACKAGED: &str = "/usr/bin/bromigos-live";

/// VECTOR's packaged launcher (`bromigos-holo`, package `bromigos-vector`), preferred over the dotfiles' when present.
pub const HOLO_BIN_PACKAGED: &str = "/usr/bin/bromigos-holo";

/// The wallpaper tool as packaged (bromigos-desktop).
pub const WALLPAPER_BIN_PACKAGED: &str = "/usr/bin/bromigos-wallpaper";

/// Every location the core uses.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Paths {
    pub home: PathBuf,
    pub runtime_dir: PathBuf,
    pub config_home: PathBuf,
    pub state_home: PathBuf,
    /// `$XDG_DATA_HOME` (`~/.local/share`): installed extensions live under it.
    pub data_home: PathBuf,
    /// `$XDG_CACHE_HOME` (`~/.cache`).
    pub cache_home: PathBuf,
    /// Read-only defaults (`/usr/share/bromigos`).
    pub share_dir: PathBuf,
    /// Packaged commands, searched before `PATH` (`/usr/lib/bromigos/bin`).
    pub lib_bin: PathBuf,
    /// The live layer's config as installed today (the dotfiles' copy).
    pub live_config: PathBuf,
    /// The user's animation switches, merged over the live config:
    /// `~/.config/bromigos/live/overrides.toml`.
    pub live_overrides: PathBuf,
    /// Where the switches used to live (`~/.local/state/bromigos-live/overrides.toml`):
    /// read when `live_overrides` is missing, moved on the first write.
    pub live_overrides_legacy: PathBuf,
    /// The live layer's launcher: the packaged `/usr/bin/bromigos-live` when installed,
    /// else the dotfiles' (`~/.config/bromigos-live/bin/bromigos-live`).
    pub live_bin: PathBuf,
    /// VECTOR's launcher: the packaged `/usr/bin/bromigos-holo` when installed, else the
    /// dotfiles' (`~/.config/bromigos/holo/bin/bromigos-holo`).
    pub holo_bin: PathBuf,
    /// The wallpaper tool: the packaged `/usr/bin/bromigos-wallpaper` when installed, else
    /// the dotfiles' (`~/.config/bromigos/bin/bromigos-wallpaper`).
    pub wallpaper_bin: PathBuf,
    /// pacman's database of installed packages (`/var/lib/pacman/local`).
    pub pacman_local: PathBuf,
}

impl Paths {
    /// From the process environment.
    pub fn from_env() -> Self {
        Self::from_lookup(|k| std::env::var_os(k).map(PathBuf::from))
    }

    /// From any variable lookup (`None` = unset). Empty or relative XDG values are
    /// ignored, as the XDG Base Directory spec says.
    pub fn from_lookup(get: impl Fn(&str) -> Option<PathBuf>) -> Self {
        let set = |k: &str| get(k).filter(|p| !p.as_os_str().is_empty());
        let xdg = |k: &str| set(k).filter(|p| p.is_absolute());
        let home = set("HOME").unwrap_or_else(|| PathBuf::from("/"));
        let runtime_dir = xdg("XDG_RUNTIME_DIR").unwrap_or_else(|| {
            PathBuf::from(format!("/run/user/{}", rustix::process::getuid().as_raw()))
        });
        let config_home = xdg("XDG_CONFIG_HOME").unwrap_or_else(|| home.join(".config"));
        let state_home = xdg("XDG_STATE_HOME").unwrap_or_else(|| home.join(".local/state"));
        let data_home = xdg("XDG_DATA_HOME").unwrap_or_else(|| home.join(".local/share"));
        let cache_home = xdg("XDG_CACHE_HOME").unwrap_or_else(|| home.join(".cache"));
        Paths {
            live_config: set("BROMIGOS_LIVE_CONFIG")
                .unwrap_or_else(|| config_home.join("bromigos-live/config.toml")),
            live_overrides: config_home.join("bromigos/live/overrides.toml"),
            live_overrides_legacy: state_home.join("bromigos-live/overrides.toml"),
            share_dir: set("BROMIGOS_SHARE_DIR")
                .unwrap_or_else(|| PathBuf::from("/usr/share/bromigos")),
            lib_bin: set("BROMIGOS_LIB_BIN")
                .unwrap_or_else(|| PathBuf::from("/usr/lib/bromigos/bin")),
            live_bin: set("BROMIGOS_LIVE_BIN")
                .or_else(|| Some(PathBuf::from(LIVE_BIN_PACKAGED)).filter(|p| p.exists()))
                .unwrap_or_else(|| config_home.join("bromigos-live/bin/bromigos-live")),
            holo_bin: set("BROMIGOS_HOLO_BIN")
                .or_else(|| Some(PathBuf::from(HOLO_BIN_PACKAGED)).filter(|p| p.exists()))
                .unwrap_or_else(|| config_home.join("bromigos/holo/bin/bromigos-holo")),
            wallpaper_bin: set("BROMIGOS_WALLPAPER_BIN")
                .or_else(|| Some(PathBuf::from(WALLPAPER_BIN_PACKAGED)).filter(|p| p.exists()))
                .unwrap_or_else(|| config_home.join("bromigos/bin/bromigos-wallpaper")),
            pacman_local: set("BROMIGOS_PACMAN_LOCAL")
                .unwrap_or_else(|| PathBuf::from("/var/lib/pacman/local")),
            home,
            runtime_dir,
            config_home,
            state_home,
            data_home,
            cache_home,
        }
    }

    /// The live config shipped as a read-only default (`/usr/share/bromigos/live/config.toml`).
    pub fn live_config_default(&self) -> PathBuf {
        self.share_dir.join("live/config.toml")
    }

    /// The desktop's read-only default configs (`/usr/share/bromigos/default`, package
    /// bromigos-desktop).
    pub fn defaults_dir(&self) -> PathBuf {
        self.share_dir.join("default")
    }

    /// The migrations `bromigos update` runs (`/usr/share/bromigos/migrations`).
    pub fn migrations_dir(&self) -> PathBuf {
        self.share_dir.join("migrations")
    }

    /// Which migrations are done, and their log (`~/.local/state/bromigos/migrations`).
    pub fn migrations_state_dir(&self) -> PathBuf {
        self.user_state_dir().join("migrations")
    }

    /// `~/.config/bromigos`: settings the user owns; updates never touch it.
    pub fn user_config_dir(&self) -> PathBuf {
        self.config_home.join("bromigos")
    }

    /// `~/.config/bromigos/profile.toml`: who the user is and what VECTOR calls them.
    pub fn profile_file(&self) -> PathBuf {
        self.user_config_dir().join("profile.toml")
    }

    /// `~/.local/state/bromigos`: generated state.
    pub fn user_state_dir(&self) -> PathBuf {
        self.state_home.join("bromigos")
    }

    /// Installed extensions (`bromigos ext`): `~/.local/share/bromigos/ext`, holding
    /// `src/<name>` (each one's checkout) and `active/<seam>` (the links the loaders read).
    /// Not under `~/.config/bromigos`, which is often a dotfiles repository.
    pub fn ext_dir(&self) -> PathBuf {
        self.data_home.join("bromigos/ext")
    }

    /// The links an enabled extension's parts get, one folder per seam:
    /// `~/.local/share/bromigos/ext/active/<seam>` (themes, bin, live, widgets, …).
    pub fn ext_active(&self, seam: &str) -> PathBuf {
        self.ext_dir().join("active").join(seam)
    }

    /// The extensions' ledger and log: `~/.local/state/bromigos/ext`.
    pub fn ext_state_dir(&self) -> PathBuf {
        self.user_state_dir().join("ext")
    }

    /// `$XDG_RUNTIME_DIR/hypr`: one directory per Hyprland instance.
    pub fn hypr_dir(&self) -> PathBuf {
        self.runtime_dir.join("hypr")
    }

    /// The live layer's control socket.
    pub fn live_socket(&self) -> PathBuf {
        self.runtime_dir.join("bromigos-live.sock")
    }

    /// The live layer's supervisor PID file (`PID START`; the daemon's own is
    /// `bromigos-live.lock`, which it holds locked).
    pub fn live_pid_file(&self) -> PathBuf {
        self.runtime_dir.join("bromigos-live.pid")
    }

    /// Present while the live layer's sounds are muted.
    pub fn live_muted(&self) -> PathBuf {
        self.live_state_dir().join("muted")
    }

    /// `$XDG_STATE_HOME/bromigos-live`.
    pub fn live_state_dir(&self) -> PathBuf {
        self.state_home.join("bromigos-live")
    }

    /// VECTOR's control socket.
    pub fn holo_socket(&self) -> PathBuf {
        self.runtime_dir.join("bromigos-holo.sock")
    }

    /// The old marker of VECTOR's terminal switch (`vector shell off`); still read as off.
    pub fn vector_shell_off(&self) -> PathBuf {
        self.user_state_dir().join("vector-shell-off")
    }

    /// The markers of VECTOR's emergency switch (`bromigos vector off`; vector's
    /// holo/vector/switch.py): any one present means he's switched off. The first survives
    /// restarts; the second is this session's (its folder can't be renamed from his sandbox).
    pub fn vector_switch_marks(&self) -> [PathBuf; 3] {
        [
            self.user_state_dir().join("vector-switch").join("off"),
            self.runtime_dir.join("bromigos-vector-switch").join("off"),
            self.vector_shell_off(),
        ]
    }

    /// Whether VECTOR's emergency switch is off: a marker there (even a dangling symlink),
    /// or a markers' folder swapped for a symlink.
    pub fn vector_switched_off(&self) -> bool {
        let marks = self.vector_switch_marks();
        marks.iter().any(|p| p.symlink_metadata().is_ok())
            || marks[..2].iter().any(|p| {
                p.parent()
                    .and_then(|d| d.symlink_metadata().ok())
                    .is_some_and(|m| m.file_type().is_symlink())
            })
    }

    /// The lock launcher's single-instance lock.
    pub fn lock_flock(&self) -> PathBuf {
        self.runtime_dir.join("bromigos-lock.flock")
    }

    /// Joins a runtime-relative name the way the shell did (`$run/$name`).
    pub fn in_runtime(&self, name: &str) -> PathBuf {
        let mut s = self.runtime_dir.clone().into_os_string();
        s.push("/");
        s.push(name);
        Path::new(&s).to_path_buf()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    fn with(vars: &[(&str, &str)]) -> Paths {
        let m: HashMap<String, PathBuf> = vars
            .iter()
            .map(|(k, v)| (k.to_string(), PathBuf::from(v)))
            .collect();
        Paths::from_lookup(|k| m.get(k).cloned())
    }

    #[test]
    fn defaults_follow_home() {
        let p = with(&[("HOME", "/h"), ("XDG_RUNTIME_DIR", "/r")]);
        assert_eq!(
            p.live_config,
            PathBuf::from("/h/.config/bromigos-live/config.toml")
        );
        assert_eq!(
            p.live_overrides,
            PathBuf::from("/h/.config/bromigos/live/overrides.toml")
        );
        assert_eq!(
            p.live_overrides_legacy,
            PathBuf::from("/h/.local/state/bromigos-live/overrides.toml")
        );
        assert_eq!(p.lib_bin, PathBuf::from("/usr/lib/bromigos/bin"));
        assert_eq!(
            p.ext_active("themes"),
            PathBuf::from("/h/.local/share/bromigos/ext/active/themes")
        );
        assert_eq!(
            p.ext_state_dir(),
            PathBuf::from("/h/.local/state/bromigos/ext")
        );
        let holo = if Path::new(HOLO_BIN_PACKAGED).exists() {
            PathBuf::from(HOLO_BIN_PACKAGED)
        } else {
            PathBuf::from("/h/.config/bromigos/holo/bin/bromigos-holo")
        };
        assert_eq!(p.holo_bin, holo);
        assert_eq!(p.live_socket(), PathBuf::from("/r/bromigos-live.sock"));
        assert_eq!(
            p.profile_file(),
            PathBuf::from("/h/.config/bromigos/profile.toml")
        );
        assert_eq!(p.lock_flock(), PathBuf::from("/r/bromigos-lock.flock"));
    }

    #[test]
    fn xdg_and_overrides() {
        let p = with(&[
            ("HOME", "/h"),
            ("XDG_CONFIG_HOME", "/c"),
            ("XDG_STATE_HOME", "relative/ignored"),
            ("BROMIGOS_LIVE_CONFIG", "/x/live.toml"),
        ]);
        assert_eq!(p.live_config, PathBuf::from("/x/live.toml"));
        let want = if Path::new(LIVE_BIN_PACKAGED).exists() {
            PathBuf::from(LIVE_BIN_PACKAGED)
        } else {
            PathBuf::from("/c/bromigos-live/bin/bromigos-live")
        };
        assert_eq!(p.live_bin, want);
        assert_eq!(p.state_home, PathBuf::from("/h/.local/state"));
    }

    #[test]
    fn vector_switch_reads_any_marker() {
        let d = tempfile::tempdir().unwrap();
        let home = d.path().join("h");
        let run = d.path().join("r");
        std::fs::create_dir_all(&run).unwrap();
        let p = with(&[
            ("HOME", home.to_str().unwrap()),
            ("XDG_RUNTIME_DIR", run.to_str().unwrap()),
        ]);
        assert!(!p.vector_switched_off());
        let [state, session, old] = p.vector_switch_marks();
        assert_eq!(state, home.join(".local/state/bromigos/vector-switch/off"));
        assert_eq!(session, run.join("bromigos-vector-switch/off"));
        for m in [&state, &session, &old] {
            std::fs::create_dir_all(m.parent().unwrap()).unwrap();
            std::fs::write(m, "").unwrap();
            assert!(p.vector_switched_off(), "{}", m.display());
            std::fs::remove_file(m).unwrap();
        }
        // a dangling symlink in a marker's place, or a swapped folder: still off
        std::os::unix::fs::symlink("/nonexistent", &state).unwrap();
        assert!(p.vector_switched_off());
        std::fs::remove_file(&state).unwrap();
        std::fs::remove_dir(session.parent().unwrap()).unwrap();
        std::os::unix::fs::symlink(d.path(), session.parent().unwrap()).unwrap();
        assert!(p.vector_switched_off());
    }
}
