//! Writing `targets.toml` (where AI work runs: docs/targets.md). Reading and resolving it
//! is `bromigos_art::targets`; this side only edits the user's file, keeping their
//! comments and other keys (`bromigos target`, `bromigos setup targets`).

use std::path::PathBuf;

use toml_edit::{Array, DocumentMut, Item, Table, value};

use crate::paths::Paths;

pub const TARGETS: [&str; 3] = ["homelab", "local", "cloud"];

pub const SERVICES: [&str; 8] = [
    "image.generate",
    "image.edit",
    "image.cutout",
    "video.loop",
    "model3d.generate",
    "voice.tts",
    "voice.stt",
    "llm",
];

/// The user's `targets.toml` (`$BROMIGOS_TARGETS_CONFIG` replaces it).
pub fn user_path(paths: &Paths) -> PathBuf {
    std::env::var_os("BROMIGOS_TARGETS_CONFIG")
        .map(PathBuf::from)
        .unwrap_or_else(|| paths.user_config_dir().join("targets.toml"))
}

const HEADER: &str = "\
# Where bromigOS's AI work runs (docs/targets.md): homelab (homelab.toml's sources), local
# (this machine) and cloud (nolgia's credits, a hosted LLM). `bromigos target` shows what
# each service would use and switches it; `bromigos target homelab|local|cloud` puts one
# first. Your other keys and comments here are kept.
";

fn check(order: &[String], services: &[String]) -> Result<(), String> {
    if order.is_empty() {
        return Err("an order needs at least one target (homelab, local, cloud)".into());
    }
    for t in order {
        if !TARGETS.contains(&t.as_str()) {
            return Err(format!("{t:?} is not a target (homelab, local, cloud)"));
        }
    }
    for (i, t) in order.iter().enumerate() {
        if order[..i].contains(t) {
            return Err(format!("{t} is listed twice"));
        }
    }
    for s in services {
        if !SERVICES.contains(&s.as_str()) {
            return Err(format!("unknown service {s:?} ({})", SERVICES.join(", ")));
        }
    }
    Ok(())
}

fn parse(existing: &str) -> Result<DocumentMut, String> {
    let mut doc: DocumentMut = existing.parse().map_err(|e| format!("targets.toml: {e}"))?;
    if existing.trim().is_empty() {
        doc.decor_mut().set_prefix(HEADER);
    }
    doc["format"] = value(1);
    Ok(doc)
}

fn array(order: &[String]) -> Array {
    let mut a = Array::new();
    for t in order {
        a.push(t.as_str());
    }
    a
}

fn table<'a>(doc: &'a mut DocumentMut, key: &str, implicit: bool) -> Result<&'a mut Table, String> {
    if !doc.contains_table(key) {
        let mut t = Table::new();
        t.set_implicit(implicit);
        doc[key] = Item::Table(t);
    }
    doc[key]
        .as_table_mut()
        .ok_or(format!("targets.toml: {key} isn't a table"))
}

/// The file with `order` set: for everything (`[targets] order`), or for each of
/// `services` (`[service."<name>"] order`).
pub fn with_order(existing: &str, order: &[String], services: &[String]) -> Result<String, String> {
    check(order, services)?;
    let mut doc = parse(existing)?;
    if services.is_empty() {
        table(&mut doc, "targets", false)?["order"] = value(array(order));
    } else {
        let svc = table(&mut doc, "service", true)?;
        for s in services {
            if !svc.contains_table(s) {
                svc[s.as_str()] = Item::Table(Table::new());
            }
            svc[s.as_str()]["order"] = value(array(order));
        }
    }
    Ok(doc.to_string())
}

/// The file without the services' own orders (all of them when `services` is empty), so
/// they follow `[targets] order` again.
pub fn without_overrides(existing: &str, services: &[String]) -> Result<String, String> {
    check(&["local".to_string()], services)?;
    let mut doc = parse(existing)?;
    if let Some(svc) = doc.get_mut("service").and_then(Item::as_table_mut) {
        if services.is_empty() {
            svc.clear();
        } else {
            for s in services {
                svc.remove(s);
            }
        }
        if svc.is_empty() {
            doc.remove("service");
        }
    }
    Ok(doc.to_string())
}

/// `first` moved to the front of `current`; the others keep their places. The cloud is
/// never added this way: it stays out unless it was already in, or is `first`.
pub fn with_first(current: &[String], first: &str, exclusive: bool) -> Vec<String> {
    if exclusive {
        return vec![first.to_string()];
    }
    let mut out = vec![first.to_string()];
    out.extend(current.iter().filter(|t| *t != first).cloned());
    out
}

/// Writes the user's file (a stow link is written through: the file it points at).
pub fn write(paths: &Paths, text: &str) -> std::io::Result<()> {
    let p = user_path(paths);
    let p = std::fs::canonicalize(&p).unwrap_or(p);
    if let Some(d) = p.parent() {
        std::fs::create_dir_all(d)?;
    }
    let tmp = p.with_extension("toml.tmp");
    std::fs::write(&tmp, text)?;
    std::fs::rename(&tmp, &p)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn s(v: &[&str]) -> Vec<String> {
        v.iter().map(|x| x.to_string()).collect()
    }

    #[test]
    fn orders_written_and_comments_kept() {
        let mine = "# mine\nformat = 1\n[targets]\norder = [\"homelab\", \"local\"]  # no cloud\n";
        let t = with_order(mine, &s(&["local", "homelab"]), &[]).unwrap();
        assert!(t.contains("# mine"));
        assert!(t.contains("order = [\"local\", \"homelab\"]"));
        let t = with_order(&t, &s(&["homelab", "local", "cloud"]), &s(&["video.loop"])).unwrap();
        assert!(t.contains("[service.\"video.loop\"]"));
        let back: toml::Table = toml::from_str(&t).unwrap();
        assert_eq!(
            back["service"]["video.loop"]["order"]
                .as_array()
                .unwrap()
                .len(),
            3
        );
        let t = without_overrides(&t, &[]).unwrap();
        assert!(!t.contains("video.loop"));
        let fresh = with_order("", &s(&["homelab"]), &[]).unwrap();
        assert!(fresh.starts_with("# Where bromigOS's AI work runs"));
        assert!(fresh.contains("format = 1"));
    }

    #[test]
    fn bad_orders_refused_and_first_moves_without_adding_the_cloud() {
        assert!(with_order("", &s(&["moon"]), &[]).is_err());
        assert!(with_order("", &s(&["local", "local"]), &[]).is_err());
        assert!(with_order("", &s(&[]), &[]).is_err());
        assert!(with_order("", &s(&["local"]), &s(&["teleport"])).is_err());
        assert_eq!(
            with_first(&s(&["homelab", "local"]), "local", false),
            s(&["local", "homelab"])
        );
        assert_eq!(
            with_first(&s(&["homelab", "local"]), "cloud", false),
            s(&["cloud", "homelab", "local"])
        );
        assert_eq!(
            with_first(&s(&["homelab", "local", "cloud"]), "local", true),
            s(&["local"])
        );
    }
}
