//! Secure Boot on an installed bromigOS (docs/secureboot.md, "The installed system").
//!
//! The work is the root helper's, `/usr/lib/bromigos/secureboot/bromigos-secureboot`
//! (package `bromigos-secureboot`): this computer's own key (root's only), GRUB built with
//! its modules and the boot theme's fonts inside and signed, the kernels and Field Kit's
//! image signed, shim (Microsoft-signed) first in the firmware's boot order, and the key's
//! enrollment asked for at the next start. Its pacman hooks sign again after every kernel,
//! GRUB, font or Field Kit update. This module is `bromigos secureboot`: which helper verb,
//! with sudo where it changes the computer (`status` needs no root).

use std::path::Path;
use std::process::Command;

/// The root helper (package bromigos-secureboot).
pub const HELPER: &str = "/usr/lib/bromigos/secureboot/bromigos-secureboot";

/// The verbs `bromigos secureboot` takes, `status` first (the default).
pub const ACTIONS: [&str; 4] = ["status", "setup", "resign", "remove"];

/// The helper's command line for an action: sudo for what changes the computer (unless
/// already root), `--json` for status, `--dry-run` and `--code` where they apply.
pub fn argv(
    action: &str,
    dry_run: bool,
    code: Option<&str>,
    json: bool,
    root: bool,
) -> Result<Vec<String>, String> {
    if !ACTIONS.contains(&action) {
        return Err(format!(
            "bromigos secureboot: {action}? (status, setup, resign or remove)"
        ));
    }
    let mut a: Vec<String> = Vec::new();
    if action != "status" && !root {
        a.push("sudo".into());
    }
    a.push(HELPER.into());
    a.push(action.into());
    if action == "status" {
        if json {
            a.push("--json".into());
        }
        if dry_run {
            return Err(
                "bromigos secureboot status: --dry-run is for setup, resign and remove".into(),
            );
        }
    } else if dry_run {
        a.push("--dry-run".into());
    }
    if let Some(c) = code {
        if action != "setup" {
            return Err("bromigos secureboot: --code is for setup".into());
        }
        if !(4..=8).contains(&c.len()) || !c.bytes().all(|b| b.is_ascii_digit()) {
            return Err(
                "bromigos secureboot: --code is 4 to 8 digits (MokManager's keyboard is always a US one: \
                 digits type the same everywhere)"
                    .into(),
            );
        }
        a.push("--code".into());
        a.push(c.into());
    }
    Ok(a)
}

/// Whether this process runs as root (the installer, a pacman hook): then no sudo.
pub fn is_root() -> bool {
    use std::os::unix::fs::MetadataExt;
    std::fs::metadata("/proc/self")
        .map(|m| m.uid() == 0)
        .unwrap_or(false)
}

/// Runs the helper with the terminal as its own (sudo may ask for a password), and returns
/// its exit code. Without the package, says how to get it.
pub fn run(action: &str, dry_run: bool, code: Option<&str>, json: bool) -> Result<i32, String> {
    let a = argv(action, dry_run, code, json, is_root())?;
    if !Path::new(HELPER).exists() {
        return Err(
            "bromigos secureboot: bromigos-secureboot isn't installed (sudo pacman -S bromigos-secureboot)".into(),
        );
    }
    let st = Command::new(&a[0])
        .args(&a[1..])
        .status()
        .map_err(|e| format!("bromigos secureboot: {}: {e}", a[0]))?;
    Ok(st.code().unwrap_or(1))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn status_needs_no_sudo() {
        let a = argv("status", false, None, true, false).unwrap();
        assert_eq!(a, vec![HELPER, "status", "--json"]);
    }

    #[test]
    fn changes_go_through_sudo_unless_root() {
        let a = argv("setup", true, Some("4827"), false, false).unwrap();
        assert_eq!(
            a,
            vec!["sudo", HELPER, "setup", "--dry-run", "--code", "4827"]
        );
        let a = argv("resign", false, None, false, true).unwrap();
        assert_eq!(a, vec![HELPER, "resign"]);
        let a = argv("remove", true, None, false, false).unwrap();
        assert_eq!(a, vec!["sudo", HELPER, "remove", "--dry-run"]);
    }

    #[test]
    fn refuses_what_doesnt_apply() {
        assert!(argv("enable", false, None, false, false).is_err());
        assert!(argv("setup", false, Some("12a4"), false, false).is_err());
        assert!(argv("setup", false, Some("123"), false, false).is_err());
        assert!(argv("resign", false, Some("1234"), false, false).is_err());
        assert!(argv("status", true, None, false, false).is_err());
    }
}
