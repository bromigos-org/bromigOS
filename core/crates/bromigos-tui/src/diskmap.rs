//! The disk map: a disk as one bar of its partitions, each a coloured segment sized by its
//! share of the disk, labelled by what's on it (bromigOS, Windows, EFI, ext4…) where the
//! segment has room, the free space dim. Field Kit's Home draws it; the installer's TUI draws
//! the same one from [`rules`] (`bromigos fieldkit shapes`, lib/bromigos_drift.py).
//!
//! The input is lsblk's (`lsblk -J -b -o NAME,PATH,SIZE,TYPE,FSTYPE,LABEL,PARTTYPENAME,…`), or
//! Field Kit's overview, which passes the same fields on: a disk's `size` in bytes and its
//! `parts` (or lsblk's `children`), each with `size`, `fstype`, `parttypename` and `label`.

use ratatui::style::{Modifier, Style};
use ratatui::text::Span;
use serde_json::{Value, json};

use crate::term::{Look, Mode};

/// What a partition can hold: its kind, its palette role, its label (empty: the filesystem's
/// name), the filesystems and the words in a partition type that say it's this kind.
pub struct Kind {
    pub kind: &'static str,
    pub role: &'static str,
    pub label: &'static str,
    pub fstypes: &'static [&'static str],
    pub parttype_words: &'static [&'static str],
}

const fn k(
    kind: &'static str,
    role: &'static str,
    label: &'static str,
    fstypes: &'static [&'static str],
    parttype_words: &'static [&'static str],
) -> Kind {
    Kind {
        kind,
        role,
        label,
        fstypes,
        parttype_words,
    }
}

/// The kinds, first match wins.
pub const KINDS: &[Kind] = &[
    k("efi", "muted", "EFI", &[], &["EFI System"]),
    k("bromigos", "primary", "bromigOS", &["crypto_LUKS"], &[]),
    k(
        "windows",
        "accent",
        "Windows",
        &["ntfs", "BitLocker"],
        &["Microsoft", "Windows"],
    ),
    k("swap", "faint", "swap", &["swap"], &["swap"]),
    k(
        "linux",
        "soft",
        "",
        &["ext4", "ext3", "ext2", "xfs", "btrfs", "f2fs", "bcachefs"],
        &["Linux"],
    ),
    k("other", "dim", "", &[], &[]),
];

fn kind(name: &str) -> Option<&'static Kind> {
    KINDS.iter().find(|k| k.kind == name)
}

/// The free space's role and label.
pub const FREE: (&str, &str) = ("faint", "free");

/// The ASCII look's fill for each kind (no colour to tell them apart), and the free space's.
pub const ASCII_FILL: &[(&str, char)] = &[
    ("efi", ':'),
    ("bromigos", '#'),
    ("windows", '='),
    ("swap", '~'),
    ("linux", '+'),
    ("other", '%'),
    ("free", '.'),
];

/// A partition's kind, from its filesystem and partition type.
pub fn kind_of(fstype: &str, parttype: &str) -> &'static str {
    let pt = parttype.to_ascii_lowercase();
    for k in KINDS {
        if k.fstypes.contains(&fstype)
            || k.parttype_words
                .iter()
                .any(|w| pt.contains(&w.to_ascii_lowercase()))
        {
            return k.kind;
        }
    }
    "other"
}

/// One segment of the bar: what it is, its label, its share in bytes.
#[derive(Debug, Clone, PartialEq)]
pub struct Seg {
    pub kind: &'static str,
    pub label: String,
    pub size: u64,
}

fn num(v: &Value) -> u64 {
    v.as_u64()
        .or_else(|| v.as_str().and_then(|s| s.parse().ok()))
        .unwrap_or(0)
}

/// A disk's segments, its partitions in order, then the space no partition uses.
pub fn segments(disk: &Value) -> Vec<Seg> {
    let parts = disk
        .get("parts")
        .or_else(|| disk.get("children"))
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let text = |p: &Value, k: &str| p[k].as_str().unwrap_or("").to_string();
    let mut out: Vec<Seg> = parts
        .iter()
        .filter(|p| num(&p["size"]) > 0)
        .map(|p| {
            let kind = kind_of(&text(p, "fstype"), &text(p, "parttypename"));
            let named = self::kind(kind).map(|k| k.label).unwrap_or("");
            let label = if !named.is_empty() {
                named.to_string()
            } else if !text(p, "fstype").is_empty() {
                text(p, "fstype")
            } else {
                text(p, "label")
            };
            Seg {
                kind,
                label,
                size: num(&p["size"]),
            }
        })
        .collect();
    let used: u64 = out.iter().map(|s| s.size).sum();
    let total = num(&disk["size"]);
    if total > used {
        out.push(Seg {
            kind: "free",
            label: FREE.1.into(),
            size: total - used,
        });
    }
    out
}

/// Each segment's cells in a bar `width` wide: its share, rounded by the largest remainder,
/// at least one cell for a partition while there's room; free space can get none.
pub fn cells(segs: &[Seg], width: usize) -> Vec<usize> {
    let total: u64 = segs.iter().map(|s| s.size).sum();
    if total == 0 || width == 0 {
        return vec![0; segs.len()];
    }
    let exact: Vec<f64> = segs
        .iter()
        .map(|s| s.size as f64 * width as f64 / total as f64)
        .collect();
    let min = |i: usize| usize::from(segs[i].kind != "free");
    let mut n: Vec<usize> = (0..segs.len())
        .map(|i| (exact[i].floor() as usize).max(min(i)))
        .collect();
    // too many: take from the biggest that can spare a cell, the first of equals first
    let first_biggest = |ok: &dyn Fn(usize) -> bool, n: &[usize]| {
        (0..n.len())
            .filter(|i| ok(*i))
            .max_by_key(|i| (n[*i], std::cmp::Reverse(*i)))
    };
    while n.iter().sum::<usize>() > width {
        let Some(i) =
            first_biggest(&|i| n[i] > min(i), &n).or_else(|| first_biggest(&|i| n[i] > 0, &n))
        else {
            break;
        };
        n[i] -= 1;
    }
    // too few: to the largest remainders, the first of equals first
    let mut order: Vec<usize> = (0..n.len()).collect();
    order.sort_by(|a, b| {
        let ra = exact[*a] - n[*a] as f64;
        let rb = exact[*b] - n[*b] as f64;
        rb.partial_cmp(&ra).unwrap_or(std::cmp::Ordering::Equal)
    });
    let mut k = 0;
    while n.iter().sum::<usize>() < width {
        n[order[k % order.len()]] += 1;
        k += 1;
    }
    n
}

/// A segment's text in `w` cells: " label " filled out with `fill` when the label fits, else
/// all fill.
fn seg_text(label: &str, w: usize, fill: char) -> (String, usize) {
    let lw = crate::layout::display_width(label);
    if !label.is_empty() && lw + 2 <= w {
        let rest: String = std::iter::repeat_n(fill, w - lw - 2).collect();
        (format!(" {label} {rest}"), lw + 2)
    } else {
        (std::iter::repeat_n(fill, w).collect(), 0)
    }
}

/// The disk's bar, `width` cells: each partition in its kind's colour, its label on it where
/// there's room, the free space in faint shade. ASCII tells kinds apart by their fill.
pub fn bar(look: &Look, disk: &Value, width: u16) -> Vec<Span<'static>> {
    let segs = segments(disk);
    let n = cells(&segs, width as usize);
    let p = &look.pal;
    let mut out = Vec::new();
    for (s, w) in segs.iter().zip(n) {
        if w == 0 {
            continue;
        }
        let role = kind(s.kind).map(|k| k.role).unwrap_or(FREE.0);
        let c = p.role(role);
        if look.ascii || look.mode == Mode::Mono {
            let fill = ASCII_FILL
                .iter()
                .find(|f| f.0 == s.kind)
                .map(|f| f.1)
                .unwrap_or('%');
            out.push(Span::raw(seg_text(&s.label, w, fill).0));
            continue;
        }
        let free = s.kind == "free";
        let (t, lw) = seg_text(&s.label, w, if free { '░' } else { '█' });
        let end = t.char_indices().nth(lw).map_or(t.len(), |(i, _)| i);
        let (label, fill) = if free {
            (Style::new().fg(p.muted), Style::new().fg(p.faint))
        } else {
            (
                Style::new().bg(c).fg(p.void).add_modifier(Modifier::BOLD),
                Style::new().fg(c),
            )
        };
        if lw > 0 {
            out.push(Span::styled(t[..end].to_string(), label));
        }
        out.push(Span::styled(t[end..].to_string(), fill));
    }
    out
}

/// The rules, for the Python TUIs to draw the same map (`bromigos fieldkit shapes`).
pub fn rules() -> Value {
    json!({
        "kinds": KINDS.iter().map(|k| json!({
            "kind": k.kind, "role": k.role, "label": k.label, "fstypes": k.fstypes,
            "parttype_words": k.parttype_words,
        })).collect::<Vec<_>>(),
        "free": {"role": FREE.0, "label": FREE.1, "fill": "░"},
        "fill": "█",
        "ascii_fill": ASCII_FILL.iter().map(|(k, c)| (k.to_string(), Value::from(c.to_string()))).collect::<serde_json::Map<_, _>>(),
        "label": "a segment shows \" label \" when the label and a space each side fit; else only its fill. A kind's label left empty is the filesystem's name, then the partition's label.",
        "match": "first kind whose fstypes has the filesystem, or one of whose parttype_words is in the partition type (any case); else other",
        "cells": "each segment's share of the width, floored; a partition gets at least one cell, free space can get none; cells over the width come off the biggest, cells left over go to the largest remainders; the first of equals first both ways",
        "colours": "a partition: its role's colour; its label in the void colour, bold, on that colour. Free space: its label muted, its fill faint.",
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn disk() -> Value {
        json!({"size": 100_000, "children": [
            {"size": 1_000, "fstype": "vfat", "parttypename": "EFI System"},
            {"size": 60_000, "fstype": "crypto_LUKS", "parttypename": "Linux filesystem"},
            {"size": 30_000, "fstype": "ntfs", "parttypename": "Microsoft basic data"},
        ]})
    }

    #[test]
    fn kinds() {
        assert_eq!(kind_of("vfat", "EFI System"), "efi");
        assert_eq!(kind_of("crypto_LUKS", "Linux filesystem"), "bromigos");
        assert_eq!(kind_of("", "Microsoft reserved"), "windows");
        assert_eq!(kind_of("ext4", ""), "linux");
        assert_eq!(kind_of("swap", "Linux swap"), "swap");
        assert_eq!(kind_of("zfs_member", ""), "other");
    }

    #[test]
    fn shares_fill_the_width() {
        let s = segments(&disk());
        assert_eq!(
            s.iter().map(|x| x.kind).collect::<Vec<_>>(),
            ["efi", "bromigos", "windows", "free"]
        );
        for w in [1usize, 3, 7, 40, 61] {
            let n = cells(&s, w);
            assert_eq!(n.iter().sum::<usize>(), w, "{w}: {n:?}");
        }
        let n = cells(&s, 40);
        assert!(n[0] >= 1, "the EFI partition shows: {n:?}");
        assert_eq!(n[1], 24, "{n:?}");
    }

    #[test]
    fn the_bar_labels_where_there_is_room() {
        let look = Look::wick();
        let t: String = bar(&look, &disk(), 40)
            .iter()
            .map(|s| s.content.to_string())
            .collect();
        assert_eq!(t.chars().count(), 40, "{t}");
        assert!(t.contains(" bromigOS ") && t.contains(" Windows "), "{t}");
        let mut look = look;
        look.ascii = true;
        let t: String = bar(&look, &disk(), 40)
            .iter()
            .map(|s| s.content.to_string())
            .collect();
        assert!(t.is_ascii() && t.contains('#') && t.contains('='), "{t}");
    }
}
