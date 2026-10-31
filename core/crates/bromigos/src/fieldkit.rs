//! `bromigos fieldkit`: Field Kit's screens (docs/fieldkit.md), in DRIFTGLASS (bromigos-tui).
//!
//! bromigOS without the desktop: Repair, Lab, Tools, Install and Shell, on the Field Kit
//! medium's console, the full medium's Field Kit entry, bromigOS Server's console and any
//! install. The screens are ours; the jobs behind them are Field Kit's engine
//! (`fieldkit-engine engine VERB`, bromigos-fieldkit-tools, JSON on standard output), which
//! drives the tools underneath (cryptsetup, btrfs, partclone, chntpw…), so nobody has to learn
//! those.
//!
//!   bromigos fieldkit                 the menu (as root: it asks sudo first)
//!   bromigos fieldkit console         the first console's loop: the menu, a shell when someone
//!                                     leaves it, the menu again
//!   bromigos fieldkit WORDS…          the engine's plain-text jobs: why, black-screen, status,
//!                                     make-stick, remote, usb, edition
//!
//! The menu is a state machine ([`App`]): keys and the engine's replies change it, and it asks
//! for work as [`Effect`]s (an engine call, a streaming job, a program to run with the screen
//! handed over). The run loop does the work; tests drive the same machine with a fake engine.

use std::ffi::OsString;
use std::io::{BufRead, BufReader, Write};
use std::os::unix::process::CommandExt;
use std::path::Path;
use std::process::{Command, Stdio};
use std::sync::mpsc;
use std::time::{Duration, Instant};

use anyhow::Result;
use bromigos_tui::widgets::{self, MenuItem, Tone, st};
use bromigos_tui::{Breakpoint, Icon, Look};
use ratatui::Frame;
use ratatui::crossterm::event::{
    self, DisableMouseCapture, EnableMouseCapture, Event, KeyCode, KeyEvent, KeyEventKind,
    KeyModifiers, MouseButton, MouseEventKind,
};
use ratatui::crossterm::execute;
use ratatui::layout::{Constraint, Layout, Rect};
use ratatui::style::{Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::Paragraph;
use serde_json::{Value, json};

pub const ENGINE: &str = "/usr/lib/bromigos/fieldkit/fieldkit-engine";
const EDITION: &str = "/usr/share/bromigos/fieldkit/edition.json";
const SERVER_STATUS: &str = "/usr/lib/bromigos/server/bromigos-server";

/// The engine's path (BROMIGOS_FIELDKIT_ENGINE for tests and checkouts).
pub fn engine_path() -> String {
    std::env::var("BROMIGOS_FIELDKIT_ENGINE").unwrap_or_else(|_| ENGINE.to_string())
}

// ------------------------------------------------------------------ the menu's contents

/// What choosing an item does.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Act {
    Mount,
    Unmount,
    Why,
    Black,
    Rollback,
    Grub,
    BootOptions,
    Edit,
    Disks,
    Backup,
    Image,
    Erase,
    Windows,
    Graphics,
    Remote,
    MakeStick,
    /// a program, the screen handed over to it
    Tool(Vec<&'static str>),
    /// a Tools card: its icon, the commands it needs (shown only when they're all there), and
    /// what it runs with the screen handed over
    Card(Icon, &'static [&'static str], &'static [&'static str]),
    AboutServer,
    PairBrodec,
    ServerUpdate,
    /// bromigos-server firewall ACTION SET: allow or deny, web or lab-cluster
    Firewall(&'static str, &'static str),
    ServerSsh,
    Containers,
    Cluster,
    Manual,
    InstallEdition(&'static str),
    Shell,
    Chroot,
    Power(&'static str),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Need {
    Any,
    Mounted,
    Lan,
    Internet,
}

#[derive(Debug, Clone)]
pub struct Item {
    pub label: &'static str,
    pub hint: &'static str,
    pub act: Act,
    pub need: Need,
}

fn it(label: &'static str, hint: &'static str, act: Act, need: Need) -> Item {
    Item {
        label,
        hint,
        act,
        need,
    }
}

pub const SECTIONS: [&str; 7] = [
    "Repair", "Lab", "VECTOR", "Tools", "Server", "Install", "Shell",
];

/// Each section's shortcut, from anywhere in Field Kit (Alt+letter while typing): R Repair,
/// L Lab, V VECTOR, T Tools, S Server, I Install, X Shell. Never printed on a tile or an item:
/// the hint bar names it when the tile is highlighted or under the pointer.
pub const SHORTCUTS: [char; 7] = ['r', 'l', 'v', 't', 's', 'i', 'x'];

/// Each section's tile on the Home screen: its icon and one line about it.
pub fn section_tile(name: &str, server_home: bool) -> (Icon, &'static str) {
    match name {
        "Repair" => (
            Icon::Repair,
            "fix an install that won't start; disks, backups, Windows",
        ),
        "Lab" => (
            Icon::Lab,
            "your homelab: the console, provisioning, models, media",
        ),
        "VECTOR" => (
            Icon::Vector,
            "ask him: he reads the logs, explains, fixes with your OK",
        ),
        "Tools" => (Icon::Tools, "monitors, editors, file recovery, the manual"),
        "Server" if server_home => (
            Icon::Server,
            "this server: updates, firewall, SSH, containers",
        ),
        "Server" => (
            Icon::Server,
            "bromigOS Server: bromigOS without the desktop, for servers",
        ),
        "Install" => (
            Icon::Install,
            "bromigOS Server here, or the desktop; a Field Kit stick",
        ),
        _ => (
            Icon::Shell,
            "a command line, remote help, restart and shut down",
        ),
    }
}

/// A section's short line about it, for a tile too narrow for section_tile's (17 columns at most).
pub fn section_tagline(name: &str, server_home: bool) -> &'static str {
    match name {
        "Repair" => "fix what's broken",
        "Lab" => "your homelab",
        "VECTOR" => "ask, he explains",
        "Tools" => "disks and images",
        "Server" if server_home => "this server",
        "Server" => "bromigOS Server",
        "Install" => "Server or desktop",
        _ => "a command line",
    }
}

/// Every item of a section, before the ones that don't apply here are left out.
pub fn section_items(section: &str) -> Vec<Item> {
    use Act::*;
    use Need::*;
    match section {
        "Repair" => vec![
            it(
                "Mount my bromigOS install",
                "unlock its disk and open it, for every repair below",
                Mount,
                Any,
            ),
            it(
                "What went wrong on the last boot?",
                "its own log, in plain words",
                Why,
                Mounted,
            ),
            it(
                "Fix a black screen / blinking cursor at startup",
                "checks the usual causes, fixes each with a backup",
                Black,
                Mounted,
            ),
            it(
                "Roll back to a snapshot",
                "start the system as it was before an update",
                Rollback,
                Mounted,
            ),
            it(
                "Repair the boot menu",
                "put GRUB back and make its menu again",
                Grub,
                Mounted,
            ),
            it(
                "Change the boot options",
                "the kernel's settings, with presets",
                BootOptions,
                Mounted,
            ),
            it(
                "Edit a file on my install",
                "with highlighting; the file is backed up first",
                Edit,
                Mounted,
            ),
            it(
                "Check disks",
                "the drives' own health, then btrfs's checks (read-only)",
                Disks,
                Any,
            ),
            it(
                "Back up my files to a USB drive",
                "every home folder, copied",
                Backup,
                Mounted,
            ),
            it(
                "Copy or image a disk",
                "a whole disk or a partition, in Clonezilla's format, checked after",
                Image,
                Any,
            ),
            it(
                "Erase a disk securely",
                "the drive's own erase, then a report on the stick",
                Erase,
                Any,
            ),
            it(
                "Windows repair",
                "a forgotten password, BitLocker, NTFS, Windows' boot entry",
                Windows,
                Any,
            ),
            it(
                "Graphics: what's in this machine",
                "the cards, their drivers and which has a monitor",
                Graphics,
                Any,
            ),
            it(
                "Unmount my install",
                "lock it again before you restart",
                Unmount,
                Mounted,
            ),
        ],
        "Lab" => vec![
            it(
                "Lab console",
                "your homelab: status, models, jobs, provisioning",
                Tool(vec!["bromigos", "lab"]),
                Lan,
            ),
            it(
                "Provision a machine",
                "set up a lab machine, step by step, reviewed before it changes anything",
                Tool(vec!["bromigos", "lab", "provision", "--guided"]),
                Lan,
            ),
            it(
                "Model catalog",
                "the best open models for your GPUs (works offline)",
                Tool(vec!["bromigos", "lab", "models", "recommend"]),
                Any,
            ),
            it(
                "Media library",
                "TV, films, music and downloads on your lab",
                Tool(vec!["bromigos", "media"]),
                Lan,
            ),
            it(
                "Network settings",
                "Wi-Fi and wired connections",
                Tool(vec!["nmtui"]),
                Any,
            ),
        ],
        "Tools" => tool_cards(),
        "Server" => vec![
            it(
                "Install bromigOS Server",
                "on this computer, with no network needed",
                InstallEdition("server"),
                Any,
            ),
            it(
                "What bromigOS Server is",
                "bromigOS without the desktop: what it runs and how it looks after itself",
                AboutServer,
                Any,
            ),
            it(
                "Pair with BRODEC",
                "this machine in BRODEC on your phone: its console, restart and update, with your fingerprint",
                PairBrodec,
                Any,
            ),
            it(
                "Update now",
                "a snapshot first; rolled back if it doesn't come back healthy",
                ServerUpdate,
                Internet,
            ),
            it(
                "Let the web in",
                "open ports 80 and 443 for a website or service",
                Firewall("allow", "web"),
                Any,
            ),
            it(
                "Close it to the web",
                "close ports 80 and 443 again",
                Firewall("deny", "web"),
                Any,
            ),
            it(
                "Let the lab's cluster in",
                "the k3s ports, from your local network only",
                Firewall("allow", "lab-cluster"),
                Any,
            ),
            it(
                "Close it to the lab's cluster",
                "close the k3s ports again",
                Firewall("deny", "lab-cluster"),
                Any,
            ),
            it(
                "SSH on or off",
                "signing in from other computers, with your key",
                ServerSsh,
                Any,
            ),
            it("Containers", "what Podman runs here", Containers, Any),
            it(
                "Join the lab's cluster",
                "become a node of your lab's k3s",
                Cluster,
                Lan,
            ),
        ],
        "Install" => vec![
            it(
                "bromigOS Server (no desktop)",
                "for servers and lab machines; no network needed",
                InstallEdition("server"),
                Any,
            ),
            it(
                "bromigOS desktop",
                "downloads about 2 GB: needs the internet",
                InstallEdition("desktop"),
                Internet,
            ),
            it(
                "Make a Field Kit USB stick",
                "with your SSH key, Wi-Fi and lab settings on it",
                MakeStick,
                Any,
            ),
        ],
        "Shell" => vec![
            it(
                "Open a shell",
                "a command line here (type exit to come back)",
                Shell,
                Any,
            ),
            it(
                "Shell inside my install",
                "a command line in the install itself (chroot)",
                Chroot,
                Mounted,
            ),
            it(
                "Remote help",
                "let someone help over SSH; shown on screen while it's on",
                Remote,
                Any,
            ),
            it("Restart", "", Power("reboot"), Any),
            it("Shut down", "", Power("poweroff"), Any),
        ],
        _ => vec![],
    }
}

/// The Tools screen's cards, from Field Kit's toolbelt: each shown only when its commands are
/// on this system, each run with the screen handed over.
/// Tools' cards a row: three, two on a narrow screen, one (a list) on a tiny one.
pub fn tool_cols(width: u16) -> usize {
    match bromigos_tui::Breakpoint::of(width) {
        bromigos_tui::Breakpoint::Wide | bromigos_tui::Breakpoint::Medium => 3,
        bromigos_tui::Breakpoint::Narrow => 2,
        bromigos_tui::Breakpoint::Tiny => 1,
    }
}

/// Home's tiles a row for a screen this wide (bromigos_tui::layout's breakpoints).
pub fn home_cols_for(width: u16) -> usize {
    match bromigos_tui::Breakpoint::of(width) {
        bromigos_tui::Breakpoint::Wide => 7,
        bromigos_tui::Breakpoint::Medium => 4,
        bromigos_tui::Breakpoint::Narrow => 3,
        bromigos_tui::Breakpoint::Tiny => 1,
    }
}

pub fn tool_cards() -> Vec<Item> {
    use Icon as I;
    let card = |label, hint, icon, needs, argv| Item {
        label,
        hint,
        act: Act::Card(icon, needs, argv),
        need: Need::Any,
    };
    vec![
        card(
            "System monitor",
            "processors, memory, disks and network, all at once (btop)",
            I::Chip,
            &["btop"],
            &["btop"],
        ),
        card(
            "Processes",
            "what's running, sorted by what it uses; stop one (htop)",
            I::List,
            &["htop"],
            &["htop"],
        ),
        card(
            "GPUs",
            "load, memory and temperature per graphics card (nvtop)",
            I::Gpu,
            &["nvtop"],
            &["nvtop"],
        ),
        card(
            "Disk I/O",
            "which programs are reading and writing the disks (iotop)",
            I::Disk,
            &["iotop"],
            &["iotop", "-o"],
        ),
        card(
            "Disk usage",
            "what fills a drive, folder by folder (gdu)",
            I::Disk,
            &["gdu"],
            &["gdu"],
        ),
        card(
            "Temperatures",
            "every sensor, read again each second (sensors)",
            I::Thermometer,
            &["sensors", "watch"],
            &["watch", "-n", "1", "sensors"],
        ),
        card(
            "Hardware report",
            "everything in this machine, in one page (inxi)",
            I::Computer,
            &["inxi", "less"],
            &["sh", "-c", "inxi -Fxxz -c 0 | less -R"],
        ),
        card(
            "Files",
            "browse with a preview: type to filter, Enter prints the path (fzf, eza, bat)",
            I::Folder,
            &["fzf"],
            &[
                "sh",
                "-c",
                "cd \"${HOME:-/}\"; fzf --walker=file,dir,hidden --preview 'bat --color=always --style=numbers {} 2>/dev/null || eza -la --tree --level=2 --color=always {} 2>/dev/null || ls -la {}'",
            ],
        ),
        card(
            "Find text",
            "search inside every file as you type; pick a line to see it (rg, fzf)",
            I::Search,
            &["rg", "fzf"],
            &[
                "sh",
                "-c",
                "fzf --ansi --disabled --delimiter : --bind 'change:reload:rg --line-number --no-heading --color=always -- {q} || true' --preview 'bat --color=always --highlight-line {2} {1} 2>/dev/null || sed -n \"{2}p\" {1}'",
            ],
        ),
        card(
            "Network test",
            "the route to a host, hop by hop, with the losses (mtr)",
            I::Network,
            &["mtr"],
            &[
                "sh",
                "-c",
                "printf 'Host to test (Enter for 1.1.1.1, or a lab machine): '; read -r h; mtr \"${h:-1.1.1.1}\"",
            ],
        ),
        card(
            "Speed test",
            "the speed to another machine that runs iperf3 -s (iperf3)",
            I::Exchange,
            &["iperf3"],
            &[
                "sh",
                "-c",
                "printf 'The other machine (it runs iperf3 -s): '; read -r h; [ -n \"$h\" ] && iperf3 -c \"$h\"; printf '\\nENTER goes back '; read -r _",
            ],
        ),
        card(
            "Wi-Fi",
            "find and join a Wi-Fi network (impala)",
            I::Wifi,
            &["impala"],
            &["impala"],
        ),
        card(
            "Network connections",
            "Wi-Fi and wired connections (nmtui)",
            I::Wired,
            &["nmtui"],
            &["nmtui"],
        ),
        card(
            "Firmware",
            "the devices whose firmware can be updated (fwupd)",
            I::Update,
            &["fwupdmgr", "less"],
            &["sh", "-c", "fwupdmgr get-devices 2>&1 | less -R"],
        ),
        card(
            "Stress test",
            "load the processors and memory for a minute, then a report (stress-ng)",
            I::Gauge,
            &["stress-ng"],
            &[
                "sh",
                "-c",
                "stress-ng --cpu 0 --vm 2 --vm-bytes 50% --timeout 60s --metrics-brief; printf '\\nENTER goes back '; read -r _",
            ],
        ),
        card(
            "Power",
            "what uses the battery, and how to save it (powertop)",
            I::Power,
            &["powertop"],
            &["powertop"],
        ),
        card(
            "Neovim",
            "LazyVim's editor, with highlighting and search (nvim)",
            I::Edit,
            &["nvim"],
            &["nvim"],
        ),
        card(
            "Micro",
            "a simple editor: Ctrl+S saves, Ctrl+Q quits (micro)",
            I::Edit,
            &["micro"],
            &["micro"],
        ),
        card(
            "Git",
            "history, changes and commits, by keys (lazygit)",
            I::Git,
            &["lazygit"],
            &["lazygit"],
        ),
        card(
            "Sessions",
            "keep work running and split the screen (tmux)",
            I::Shell,
            &["tmux"],
            &["tmux"],
        ),
        card(
            "Herdr",
            "shared terminals for people and agents (herdr)",
            I::Remote,
            &["herdr"],
            &["herdr"],
        ),
        card(
            "Bluetooth",
            "pair and connect (bromigos bluetooth tui)",
            I::Bluetooth,
            &["bromigos"],
            &["bromigos", "bluetooth", "tui"],
        ),
        card(
            "Recover files",
            "find deleted files on a drive or a card (PhotoRec)",
            I::Rollback,
            &["photorec"],
            &["photorec"],
        ),
        card(
            "Partition table",
            "find lost partitions and put them back (TestDisk)",
            I::Disk,
            &["testdisk"],
            &["testdisk"],
        ),
        card(
            "Partitions",
            "see and change a drive's partitions (cfdisk)",
            I::Disk,
            &["cfdisk"],
            &["cfdisk"],
        ),
        Item {
            label: "The bromigOS manual",
            hint: "readable here, offline",
            act: Act::Manual,
            need: Need::Any,
        },
    ]
}

/// Field Kit's toolbelt, for the Shell's keys page: what each command is for, in a line.
pub const TOOLBELT: &[(&str, &[(&str, &str)])] = &[
    (
        "Finding and reading",
        &[
            ("fzf", "pick anything from a list as you type"),
            ("rg", "search the text in files, fast"),
            ("fd", "find files by name"),
            ("bat", "read a file with highlighting and line numbers"),
            ("eza, tree", "list files, as a tree too"),
            ("z", "jump to a folder you've been to (zoxide)"),
            ("jq, yq", "read and change JSON and YAML"),
            ("file", "what kind of file it is"),
            ("tldr", "short examples for a command"),
            ("man", "a command's full manual"),
        ],
    ),
    (
        "Network",
        &[
            ("curl, wget", "download a file"),
            ("aria2c", "download faster, several parts at once"),
            (
                "ssh, mosh",
                "sign in to another machine (mosh survives a bad link)",
            ),
            ("rsync", "copy folders, only what changed"),
            ("rclone", "cloud storage and shares"),
            ("sshfs", "another machine's folder as a local one"),
            ("socat, nc", "raw connections, for testing a port"),
            (
                "ip, ping, dig",
                "addresses and routes; is it there; what a name points to",
            ),
            ("traceroute, mtr", "the route to a host"),
            ("nmap", "what's on the network, and what it answers on"),
            ("tcpdump", "watch the traffic"),
            ("iperf3", "the speed between two machines"),
            ("ethtool", "the cable's link and speed"),
            ("iw, iwctl, impala", "Wi-Fi"),
            ("wg, tailscale", "WireGuard and Tailscale tunnels"),
            ("smbclient, mount.cifs", "Windows and Samba shares"),
            ("mount.nfs", "NFS shares"),
        ],
    ),
    (
        "Disks and files",
        &[
            ("parted, gdisk", "partition tables"),
            ("cryptsetup", "encrypted disks (LUKS)"),
            ("lvm, mdadm", "volume groups and software RAID"),
            (
                "btrfs",
                "bromigOS's file system: subvolumes, snapshots, scrub",
            ),
            ("mkfs.*", "make a file system"),
            ("smartctl, nvme", "a drive's own health"),
            ("hdparm", "ATA drive settings and secure erase"),
            (
                "photorec, testdisk",
                "recover deleted files; find lost partitions",
            ),
            ("ddrescue", "copy a failing drive, the readable parts first"),
            ("partclone", "images of partitions (Clonezilla's format)"),
            ("nwipe", "erase a drive for good"),
            ("fsarchiver", "archive a file system and restore it"),
            ("mksquashfs", "pack a folder into a squashfs image"),
            ("7z, zip, unzip", "archives"),
            ("zstd, xz, pigz", "compress and decompress"),
        ],
    ),
    (
        "System and debugging",
        &[
            ("btop, htop, nvtop", "what's running; what the GPUs do"),
            ("iotop, iostat, sar", "disk activity, and its history"),
            ("lsof", "which program has a file open"),
            (
                "strace, ltrace, gdb",
                "what a program does, call by call; a debugger",
            ),
            ("sensors", "temperatures and fans"),
            ("dmidecode, lshw, inxi, hwinfo", "what the hardware is"),
            ("lspci, lsusb", "the cards and the USB devices"),
            ("efibootmgr", "the firmware's boot entries"),
            ("mokutil, sbctl", "Secure Boot: its keys and its state"),
            ("fwupdmgr", "firmware updates"),
            ("memtester", "test the memory from here"),
            ("stress-ng", "load the machine, to test it"),
            ("powertop", "what uses the battery"),
        ],
    ),
    (
        "Editing",
        &[
            ("nvim", "LazyVim's editor"),
            ("micro, nano", "simple editors"),
            ("git, lazygit", "version control"),
            (
                "tmux, herdr",
                "sessions that keep running, shared terminals",
            ),
            ("python", "Python 3"),
        ],
    ),
    (
        "Windows",
        &[
            ("chntpw", "reset a local account's password"),
            ("wimlib-imagex", "Windows images (.wim)"),
            ("ntfsfix", "fix common NTFS problems"),
            ("dislocker", "read a BitLocker drive with its key"),
        ],
    ),
    (
        "Security",
        &[
            ("gpg", "sign, check and encrypt"),
            ("age", "encrypt a file, simply"),
        ],
    ),
];

// ------------------------------------------------------------------ the state machine

/// What the menu asks the run loop to do.
#[derive(Debug, Clone, PartialEq)]
pub enum Effect {
    /// `fieldkit-engine engine ARGS`, its JSON back to [`App::reply`] for `then`
    Call {
        then: Then,
        args: Vec<String>,
        stdin: Option<String>,
    },
    /// the same, with progress lines to [`App::progress`] first
    Stream { then: Then, args: Vec<String> },
    /// a program, with the screen handed over until it ends
    Exec(Vec<String>),
    /// text to the terminal's clipboard (OSC 52)
    Copy(String),
    /// this machine's server facts (hostname, addresses, SSH, bromigos-server status)
    Server,
    /// the lab's status (`bromigos lab status --json`), for the Lab screen
    Lab,
    /// VECTOR's screen (fieldkit_vector), the menu's handed over to it until it ends
    Vector,
    /// PAIR WITH BRODEC (fieldkit_vector::pair), the menu's handed over to it until it ends
    Pair,
    /// leave the menu: "shell", "reboot", "poweroff", or nothing
    Quit(Option<String>),
}

/// What a reply is for.
#[derive(Debug, Clone, PartialEq)]
pub enum Then {
    Status,
    /// `engine plan …`: the commands panel for this title
    Plan {
        title: String,
        cli: String,
    },
    Overview,
    /// quiet fetches for a screen's left side: the drives' health, the snapshots
    DisksQuiet,
    SnapshotsQuiet,
    Installs,
    Mounted,
    Message(String),
    Findings {
        title: String,
        check: String,
    },
    Fixed {
        check: String,
        id: String,
    },
    Snapshots,
    BootOptions,
    EditCandidates,
    EditOpen,
    Disks,
    BackupTargets,
    Graphics,
    Remote,
    /// a disk list for imaging or erasing, then this step
    DiskPick(Flow),
    /// `image list`, then this step ("restore" or "verify")
    ImageList(String),
    /// `image targets`, for an image of SOURCE
    ImageTargets(String),
    /// `image mount-share`, then the image of SOURCE goes there
    ShareMounted(String),
    ErasePlan(String),
    WindowsFind,
    WindowsUsers(String),
    BootEntries,
}

/// The multi-step jobs that pick a disk first.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Flow {
    /// the disk or partition to image ("create") or copy ("clone")
    ImageSource(String),
    /// the disk to restore IMAGE onto, or to copy SOURCE onto ("restore", "clone")
    ImageTarget {
        action: String,
        from: String,
    },
    Erase,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Finding {
    pub id: String,
    pub title: String,
    pub detail: String,
    pub fix: String,
    pub ok: bool,
    pub result: String,
    /// when its fix ran and worked (the ✓ flashes for a second after: a Spark)
    pub fixed_at: Option<Instant>,
    /// the fix's exact commands, and what it touches (the engine's)
    pub commands: Vec<String>,
    pub touches: Vec<String>,
}

/// A screen over the menu.
#[derive(Debug, Clone, PartialEq)]
pub enum Overlay {
    /// an action's exact commands, what it touches, the same from the command line; copy them
    /// (OSC 52) or run them step by step in the shell
    Commands {
        title: String,
        commands: Vec<String>,
        touches: Vec<String>,
        cli: String,
        note: String,
        sel: usize,
    },
    /// `?` / F1: every key the screen under it takes
    Keys {
        title: String,
        rows: Vec<(String, String)>,
        scroll: usize,
    },
    Message {
        title: String,
        text: String,
        ok: bool,
    },
    Busy {
        title: String,
    },
    Findings {
        title: String,
        check: String,
        items: Vec<Finding>,
        sel: usize,
    },
    Pick {
        title: String,
        options: Vec<(String, String)>,
        sel: usize,
        then: Pick,
    },
    Input {
        title: String,
        prompt: String,
        value: String,
        hidden: bool,
        then: Pick,
    },
    Confirm {
        question: String,
        detail: String,
        yes: String,
        sel: usize,
        then: Pick,
    },
    Typed {
        question: String,
        detail: String,
        want: String,
        typed: String,
        then: Pick,
    },
    Progress {
        title: String,
        lines: Vec<String>,
        pct: Option<u8>,
        done: Option<(bool, String)>,
    },
    BootOptions {
        words: Vec<String>,
        presets: Vec<(String, String, String)>,
        on: Vec<bool>,
        sel: usize,
        other: String,
    },
}

/// What a choice in a dialog leads to.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Pick {
    MountDevice,
    Passphrase(String),
    Snapshot,
    RollbackYes(String),
    GrubYes,
    EditFile,
    EditTyped,
    BackupDrive,
    ImageAction,
    /// a source for "create" or "clone" (the action)
    ImageSource(String),
    /// where the image of SOURCE goes ("__share__": a share on the local network)
    ImageDest(String),
    ShareUrl(String),
    ShareUser {
        source: String,
        url: String,
    },
    SharePass {
        source: String,
        url: String,
        user: String,
    },
    /// an image chosen for "restore" or "verify"
    ImageChosen(String),
    /// the disk restored or copied onto: typed confirmation next
    ImageTarget {
        action: String,
        from: String,
    },
    ImageTyped {
        action: String,
        from: String,
        target: String,
    },
    EraseDisk,
    EraseMethod {
        dev: String,
        name: String,
        detail: String,
    },
    EraseTyped {
        dev: String,
        method: String,
    },
    WindowsAction,
    WindowsUser {
        part: String,
        warning: String,
    },
    WindowsResetYes {
        part: String,
        user: String,
    },
    WindowsKey(String),
    BootFix,
    Power(String),
    RemoteToggle(bool),
}

pub struct App {
    pub look: Look,
    pub section: usize,
    pub sel: usize,
    pub status: Value,
    pub server: Value,
    pub overlays: Vec<Overlay>,
    pub spark_until: Option<Instant>,
    pub tick: u64,
    /// Home, or a section's own screen
    pub screen: Screen,
    /// the Home screen's chosen tile (0..6) or suggestion
    pub home: HomeSel,
    /// `engine overview`: the network, SSH, this computer, what's on its drives, suggestions
    pub overview: Value,
    /// each temperature's recent readings (by its label, oldest first), kept across the
    /// overview's refreshes for Home's sparklines
    pub temps: Vec<(String, Vec<f64>)>,
    /// the last frame's size (mouse clicks find the tiles in it)
    pub size: Rect,
    /// `engine disks`, for the Repair screen's DISKS panel and the install's disk step
    pub disks: Value,
    pub snap_count: Option<usize>,
    /// problems the last black-screen check found (the Repair screen's badge)
    pub black_count: Option<usize>,
    /// `bromigos lab status --json`
    pub lab: Value,
    /// bromigOS Server's edition (/usr/share/bromigos/fieldkit/edition.json)
    pub edition: Value,
    /// the Home tile under the mouse pointer (the hint bar names it)
    pub hover: Option<usize>,
    /// where commands are looked for (tests; else PATH)
    pub path: Option<Vec<std::path::PathBuf>>,
    /// where the steps file goes (/run/bromigos-fieldkit)
    pub run_dir: std::path::PathBuf,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Screen {
    Home,
    Section,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HomeSel {
    Tile(usize),
    Suggestion(usize),
}

fn s(v: &Value, k: &str) -> String {
    v.get(k)
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string()
}

fn args(words: &[&str]) -> Vec<String> {
    words.iter().map(|w| w.to_string()).collect()
}

impl App {
    pub fn new(look: Look) -> App {
        App {
            look,
            section: 0,
            sel: 0,
            status: Value::Null,
            server: Value::Null,
            overlays: Vec::new(),
            spark_until: None,
            tick: 0,
            screen: Screen::Home,
            home: HomeSel::Tile(0),
            overview: Value::Null,
            temps: Vec::new(),
            size: Rect::new(0, 0, 100, 30),
            disks: Value::Null,
            snap_count: None,
            black_count: None,
            lab: Value::Null,
            hover: None,
            path: None,
            run_dir: std::path::PathBuf::from("/run/bromigos-fieldkit"),
            edition: std::fs::read_to_string(EDITION)
                .ok()
                .and_then(|t| serde_json::from_str(&t).ok())
                .unwrap_or(Value::Null),
        }
    }

    /// A section's own screen (Home › name).
    pub fn open_section(&mut self, i: usize) -> Vec<Effect> {
        let i = i.min(SECTIONS.len() - 1);
        self.home = HomeSel::Tile(i);
        if SECTIONS[i] == "VECTOR" {
            return vec![Effect::Vector];
        }
        self.section = i;
        self.sel = 0;
        self.screen = Screen::Section;
        let quiet = |then, a: &[&str]| Effect::Call {
            then,
            args: args(a),
            stdin: None,
        };
        match SECTIONS[i] {
            "Repair" => {
                let mut fx = vec![quiet(Then::DisksQuiet, &["disks"])];
                if self.target().is_some() {
                    fx.push(quiet(Then::SnapshotsQuiet, &["snapshots"]));
                }
                fx
            }
            "Install" => vec![quiet(Then::DisksQuiet, &["disks"])],
            "Lab" if self.net() != "none" => vec![Effect::Lab],
            _ => vec![],
        }
    }

    /// Home's tiles a row: all seven on a wide screen, four then three on a medium one, three a row
    /// on a narrow one, and a list (one a row) on a tiny one.
    pub fn home_cols(&self) -> usize {
        home_cols_for(self.size.width)
    }

    /// An item's badge: a count or a state, only when it's known (never filler).
    pub fn badge(&self, i: &Item) -> Option<(String, Tone)> {
        // what it needs first, the same on every item (mount your install first, the network)
        let why = self.blocked(i);
        if !why.is_empty() {
            return Some((why, Tone::Warn));
        }
        match &i.act {
            Act::Black => self.black_count.map(|n| {
                if n == 0 {
                    ("nothing found".into(), Tone::Good)
                } else {
                    (format!("{n} found"), Tone::Warn)
                }
            }),
            Act::Rollback => self
                .snap_count
                .map(|n| (format!("{n} snapshots"), Tone::Calm)),
            Act::BootOptions => Some(("presets".into(), Tone::Calm)),
            Act::Image => Some(("Clonezilla format".into(), Tone::Calm)),
            Act::Windows => self.overview["found"]
                .as_array()
                .into_iter()
                .flatten()
                .any(|f| f["kind"] == "windows")
                .then(|| ("Windows found".into(), Tone::Calm)),
            Act::Remote => self.status["remote"]["on"]
                .as_bool()
                .filter(|o| *o)
                .map(|_| ("ON".into(), Tone::Warn)),
            Act::ServerSsh => self.server["ssh"].as_bool().map(|on| {
                if on {
                    ("on".into(), Tone::Good)
                } else {
                    ("off".into(), Tone::Calm)
                }
            }),
            Act::InstallEdition("server") => Some(("no internet needed".into(), Tone::Good)),
            _ => None,
        }
    }

    /// The engine's suggestions (never filler: only what it found).
    pub fn suggestions(&self) -> Vec<(String, String)> {
        self.overview["suggestions"]
            .as_array()
            .into_iter()
            .flatten()
            .filter(|x| !s(x, "text").is_empty())
            .map(|x| (s(x, "text"), s(x, "action")))
            .collect()
    }

    /// A suggestion's action: the Repair item it names.
    fn suggestion(&mut self, i: usize) -> Vec<Effect> {
        let Some((_, action)) = self.suggestions().get(i).cloned() else {
            return vec![];
        };
        let act = match action.as_str() {
            "mount" => Act::Mount,
            "why" => Act::Why,
            "black" => Act::Black,
            "disks" => Act::Disks,
            "backup" => Act::Backup,
            _ => return vec![],
        };
        let mut fx = self.open_section(0);
        if let Some(it) = section_items("Repair").into_iter().find(|it| it.act == act) {
            if let Some(at) = self.items().iter().position(|x| x.act == act) {
                self.sel = at;
            }
            fx.extend(self.choose(&it));
        }
        fx
    }

    /// What to ask for when the menu opens: where Field Kit is, and the server's facts.
    pub fn start(&self) -> Vec<Effect> {
        vec![
            Effect::Call {
                then: Then::Status,
                args: args(&["status"]),
                stdin: None,
            },
            Effect::Call {
                then: Then::Overview,
                args: args(&["overview"]),
                stdin: None,
            },
            Effect::Server,
        ]
    }

    pub fn live(&self) -> bool {
        self.status["live"].as_bool().unwrap_or(false)
    }

    /// "internet", "lan" or "none": the overview's (newer, every 15 s), else the status's.
    pub fn net(&self) -> String {
        let o = s(&self.overview["network"], "state");
        if o.is_empty() {
            s(&self.status, "network")
        } else {
            o
        }
    }

    pub fn target(&self) -> Option<&Value> {
        self.status.get("target").filter(|t| t.is_object())
    }

    fn mounted_by_us(&self) -> bool {
        self.target()
            .and_then(|t| t["mounted_by_fieldkit"].as_bool())
            .unwrap_or(false)
    }

    pub fn server_home(&self) -> bool {
        !self.live() && self.server["server"].as_bool().unwrap_or(false)
    }

    /// The items of the current section that apply here.
    pub fn items(&self) -> Vec<Item> {
        let name = SECTIONS[self.section];
        section_items(name)
            .into_iter()
            .filter(|i| match &i.act {
                Act::Mount => self.live() && !self.mounted_by_us(),
                Act::Unmount => self.mounted_by_us(),
                Act::InstallEdition(_) => self.live(),
                Act::Card(_, needs, _) => needs.iter().all(|c| self.has(c)),
                // the Server section: on a medium, installing it; on a server, running it
                Act::AboutServer => !self.server_home(),
                Act::ServerUpdate
                | Act::Firewall(..)
                | Act::ServerSsh
                | Act::Containers
                | Act::Cluster => self.server_home(),
                _ => true,
            })
            .collect()
    }

    /// Why an item can't run now, in words; empty when it can.
    pub fn blocked(&self, i: &Item) -> String {
        match i.need {
            Need::Mounted if self.target().is_none() => "mount your install first".into(),
            Need::Internet if self.net() != "internet" => "needs the internet".into(),
            Need::Lan if self.net() == "none" => "needs your local network".into(),
            _ => String::new(),
        }
    }

    fn message(&mut self, title: &str, text: &str, ok: bool) {
        if let Some(Overlay::Busy { .. }) = self.overlays.last() {
            self.overlays.pop();
        }
        self.overlays.push(Overlay::Message {
            title: title.into(),
            text: text.into(),
            ok,
        });
        if ok {
            self.spark();
        }
    }

    /// DRIFTGLASS's Spark: the panel's edge glows for a second (never under reduced motion).
    pub fn spark(&mut self) {
        if self.look.motion {
            self.spark_until = Some(Instant::now() + Duration::from_secs(1));
        }
    }

    fn busy(&mut self, title: &str) {
        self.overlays.push(Overlay::Busy {
            title: title.into(),
        });
    }

    fn call(&mut self, title: &str, then: Then, a: &[&str]) -> Vec<Effect> {
        self.busy(title);
        vec![Effect::Call {
            then,
            args: args(a),
            stdin: None,
        }]
    }

    // -------------------------------------------------------------- keys

    pub fn key(&mut self, k: KeyEvent) -> Vec<Effect> {
        if k.kind != KeyEventKind::Press {
            return vec![];
        }
        if k.code == KeyCode::Char('c')
            && k.modifiers.contains(KeyModifiers::CONTROL)
            && self.overlays.is_empty()
        {
            return vec![self.quit()];
        }
        if k.code == KeyCode::F(1)
            || (k.code == KeyCode::Char('?')
                && !self.typing()
                && !matches!(self.overlays.last(), Some(Overlay::Keys { .. })))
        {
            self.show_keys();
            return vec![];
        }
        if let Some(i) = self.hotkey(&k) {
            // X: a shell, from anywhere; the screen (and its dialog) is there again after exit
            if SECTIONS[i] == "Shell" {
                return vec![self.shell()];
            }
            self.overlays.clear();
            return self.open_section(i);
        }
        if k.code == KeyCode::Char('c')
            && !self.typing()
            && k.modifiers.is_empty()
            && let Some(fx) = self.commands_here()
        {
            return fx;
        }
        if !self.overlays.is_empty() {
            return self.overlay_key(k);
        }
        match self.screen {
            Screen::Home => self.home_key(k),
            Screen::Section => self.section_key(k),
        }
    }

    /// Whether a command is on this system (PATH, or the test's folders).
    pub fn has(&self, cmd: &str) -> bool {
        match &self.path {
            Some(dirs) => dirs.iter().any(|d| d.join(cmd).is_file()),
            None => which(cmd),
        }
    }

    /// A shell, with the screen handed over: exiting it comes back here.
    pub fn shell(&self) -> Effect {
        Effect::Exec(vec![
            std::env::var("SHELL").unwrap_or_else(|_| "/bin/bash".into()),
            "-l".into(),
        ])
    }

    /// `c`: the commands of what's highlighted, if it has any: a finding, a confirm dialog's
    /// action, a section's action.
    fn commands_here(&mut self) -> Option<Vec<Effect>> {
        match self.overlays.last() {
            Some(Overlay::Findings {
                title,
                items,
                sel,
                check,
            }) => {
                let f = items.get(*sel)?.clone();
                let cli = format!("bromigos fieldkit repair {check} --dry-run");
                let title = format!("{title}: {}", f.title);
                let (commands, note) = if f.commands.is_empty() {
                    (
                        vec![],
                        "This one only reads; it has no commands of its own.".to_string(),
                    )
                } else {
                    (f.commands.clone(), String::new())
                };
                self.overlays.push(Overlay::Commands {
                    title,
                    commands,
                    touches: f.touches.clone(),
                    cli,
                    note,
                    sel: 0,
                });
                Some(vec![])
            }
            Some(Overlay::Confirm { question, then, .. }) => {
                let (q, src) = (question.clone(), pick_plan(then)?);
                Some(self.show_plan(&q, src))
            }
            Some(_) => None,
            None if self.screen == Screen::Section => {
                let it = self.items().get(self.sel)?.clone();
                let src = self.item_plan(&it)?;
                Some(self.show_plan(it.label, src))
            }
            None => None,
        }
    }

    fn show_plan(&mut self, title: &str, src: PlanSrc) -> Vec<Effect> {
        match src {
            PlanSrc::Local {
                commands,
                touches,
                cli,
                note,
            } => {
                self.overlays.push(Overlay::Commands {
                    title: title.into(),
                    commands,
                    touches,
                    cli,
                    note,
                    sel: 0,
                });
                vec![]
            }
            PlanSrc::Engine { args, cli } => {
                self.busy("Asking for the exact commands");
                vec![Effect::Call {
                    then: Then::Plan {
                        title: title.into(),
                        cli,
                    },
                    args,
                    stdin: None,
                }]
            }
        }
    }

    /// A section action's commands: the engine's plan for the repairs that change something,
    /// the command itself for the rest.
    pub fn item_plan(&self, it: &Item) -> Option<PlanSrc> {
        let eng = |a: &[&str], cli: &str| PlanSrc::Engine {
            args: args(a),
            cli: cli.into(),
        };
        let found_install = self.overview["found"]
            .as_array()
            .into_iter()
            .flatten()
            .find(|f| f["kind"] == "bromigos")
            .map(|f| format!("/dev/{}", s(f, "device")));
        Some(match &it.act {
            Act::Mount => match found_install {
                Some(dev) => PlanSrc::Engine {
                    args: vec!["plan".into(), "mount".into(), dev.clone()],
                    cli: format!("bromigos fieldkit mount {dev} --dry-run"),
                },
                None => local(
                    &[],
                    &["the disk you choose"],
                    "bromigos fieldkit mount DEVICE --dry-run",
                    "Choose the disk first: its commands show then.",
                ),
            },
            Act::Unmount => eng(&["plan", "unmount"], "bromigos fieldkit unmount --dry-run"),
            Act::Why => local(
                &["journalctl -D /mnt/bromigos/var/log/journal -b 0 -p err"],
                &["reads only"],
                "bromigos fieldkit repair last-boot",
                "",
            ),
            Act::Black => local(
                &[],
                &["reads only; each fix names its files"],
                "bromigos fieldkit repair black-screen --dry-run",
                "Open it: each problem it finds has its own commands (c on the problem).",
            ),
            Act::Rollback => local(
                &[],
                &["the install's root and /boot's kernel"],
                "bromigos fieldkit repair rollback N --dry-run",
                "Choose a snapshot first: its confirmation shows the commands for it.",
            ),
            Act::Grub => eng(
                &["plan", "grub-repair"],
                "bromigos fieldkit repair boot-menu --dry-run",
            ),
            Act::BootOptions => eng(
                &["plan", "boot-options"],
                "bromigos fieldkit repair boot-options --dry-run",
            ),
            Act::Disks => eng(&["plan", "scrub"], "bromigos fieldkit scrub --dry-run"),
            Act::Backup => local(
                &[],
                &["the USB drive you choose"],
                "bromigos fieldkit backup DEVICE --dry-run",
                "Choose the drive first: its commands show then.",
            ),
            Act::Tool(argv) => local(
                &[&argv.iter().map(|a| shq(a)).collect::<Vec<_>>().join(" ")],
                &[],
                &argv.join(" "),
                "",
            ),
            Act::Card(_, _, argv) => {
                let line = argv.iter().map(|a| shq(a)).collect::<Vec<_>>().join(" ");
                local(&[&line], &[], &line, "")
            }
            Act::ServerUpdate => local(
                &[&format!("{SERVER_STATUS} update --now")],
                &["packages, after a snapshot"],
                "bromigos-server update --now",
                "",
            ),
            Act::Firewall(what, set) => {
                let line = format!("{SERVER_STATUS} firewall {what} {set}");
                local(
                    &[&line],
                    &[&format!("the nftables rule set {set}")],
                    &format!("bromigos-server firewall {what} {set}"),
                    "",
                )
            }
            Act::ServerSsh => {
                let on = self.server["ssh"].as_bool().unwrap_or(false);
                let line = format!(
                    "systemctl {} --now sshd.service",
                    if on { "disable" } else { "enable" }
                );
                local(&[&line], &["sshd.service"], &line, "")
            }
            Act::Containers => local(&["podman ps --all"], &["reads only"], "podman ps --all", ""),
            Act::Cluster => local(
                &["bromigos lab provision add-node"],
                &["this server joins the lab's k3s"],
                "bromigos lab provision add-node",
                "Run on the computer with your lab's settings.",
            ),
            Act::Power(p) => local(
                &[&format!("systemctl {p}")],
                &["the whole machine"],
                &format!("systemctl {p}"),
                "",
            ),
            Act::Remote => local(
                &["fieldkit-engine remote on"],
                &[
                    "sshd.service",
                    "/etc/ssh/sshd_config.d/20-bromigos-remote.conf",
                ],
                "bromigos fieldkit remote on",
                "",
            ),
            Act::InstallEdition(e) => local(
                &["bromigos-iso-install --text"],
                &["the disk you choose in the installer"],
                "bromigos-iso-install --text",
                if *e == "server" {
                    "the installer's edition step: bromigOS Server (preselected on the Field Kit stick)"
                } else {
                    "the installer's edition step: the desktop (downloaded while it installs)"
                },
            ),
            Act::MakeStick => local(
                &["bromigos fieldkit make-stick DEVICE"],
                &["everything on the USB drive"],
                "bromigos fieldkit make-stick DEVICE",
                "",
            ),
            _ => return None,
        })
    }

    /// The steps file for a commands panel, and the shell that offers them one by one.
    pub fn steps(
        &self,
        title: &str,
        commands: &[String],
        touches: &[String],
        cli: &str,
    ) -> std::io::Result<Effect> {
        std::fs::create_dir_all(&self.run_dir)?;
        let sh = self.run_dir.join("steps.sh");
        let mut text = format!(
            "#!/bin/sh\n# bromigOS Field Kit: {title}\n# What it touches: {}\n# The same from the command line: {cli}\n\
             # Nothing here has run yet. In the shell, \u{2191} brings each step back, Enter runs it.\n\n",
            if touches.is_empty() {
                "nothing it changes".to_string()
            } else {
                touches.join(", ")
            }
        );
        for c in commands {
            text.push_str(c);
            text.push('\n');
        }
        std::fs::write(&sh, &text)?;
        let rc = self.run_dir.join("steps.rc");
        let mut rct = String::from("[ -f \"$HOME/.bashrc\" ] && . \"$HOME/.bashrc\"\n");
        rct.push_str(&format!(
            "printf '\\n%s\\n\\n' {}\ncat {}\n",
            shq(&format!("Field Kit: the steps for {title}. Up brings each one back, Enter runs it, exit goes back to Field Kit.")),
            shq(&sh.to_string_lossy())
        ));
        // the history, last first, so the first step is the first Up
        for c in commands.iter().rev() {
            rct.push_str(&format!("history -s {}\n", shq(c)));
        }
        std::fs::write(&rc, rct)?;
        Ok(Effect::Exec(vec![
            "bash".into(),
            "--rcfile".into(),
            rc.to_string_lossy().to_string(),
            "-i".into(),
        ]))
    }

    /// A text field has the keys: letters are text there (Alt+letter still jumps).
    pub fn typing(&self) -> bool {
        match self.overlays.last() {
            Some(Overlay::Input { .. } | Overlay::Typed { .. }) => true,
            Some(Overlay::BootOptions { sel, presets, .. }) => *sel == presets.len(),
            _ => false,
        }
    }

    /// The section a key jumps to: its letter, or Alt+letter while typing; never while a job
    /// is running (its panel stays until it's done).
    fn hotkey(&self, k: &KeyEvent) -> Option<usize> {
        let KeyCode::Char(c) = k.code else {
            return None;
        };
        if k.modifiers.contains(KeyModifiers::CONTROL) {
            return None;
        }
        let alt = k.modifiers.contains(KeyModifiers::ALT);
        if !alt && self.typing() {
            return None;
        }
        if matches!(
            self.overlays.last(),
            Some(Overlay::Busy { .. } | Overlay::Progress { done: None, .. })
        ) {
            return None;
        }
        SHORTCUTS.iter().position(|s| *s == c.to_ascii_lowercase())
    }

    /// The keys page for the screen under it.
    fn show_keys(&mut self) {
        let mut rows: Vec<(String, String)> = vec![
            ("R  L  V  T".into(), "Repair, Lab, VECTOR, Tools".into()),
            ("S  I".into(), "Server, Install".into()),
            ("X".into(), "a shell; exit it and you're back here, as you left it".into()),
            ("c".into(), "the exact commands of the highlighted action or finding, what they touch, copy or run them step by step".into()),
            (
                "Alt+letter".into(),
                "the same, while you're typing in a field".into(),
            ),
        ];
        let screen: Vec<(&str, &str)> = match self.screen {
            Screen::Home => vec![
                ("arrows", "move between the sections"),
                ("Enter", "open the highlighted section"),
                ("1 to 7", "open a section by its place"),
                ("f", "do the suggested fix, when there is one"),
                ("q, Esc", "leave the menu"),
            ],
            Screen::Section if SECTIONS[self.section] == "Tools" => vec![
                ("arrows", "move between the tools"),
                (
                    "Enter",
                    "open the tool (the screen comes back when it ends)",
                ),
                ("Esc, q", "back to Home"),
            ],
            Screen::Section => vec![
                ("up, down", "move between the actions"),
                ("Enter", "do the highlighted action"),
                ("Esc, q, Backspace", "back to Home"),
                ("click", "an action does it"),
            ],
        };
        rows.extend(
            screen
                .into_iter()
                .map(|(a, b)| (a.to_string(), b.to_string())),
        );
        rows.push(("?, F1".into(), "this page".into()));
        rows.push(("Ctrl+C".into(), "leave the menu".into()));
        let title = match self.screen {
            Screen::Home => "Keys · Home".to_string(),
            Screen::Section => format!("Keys · {}", SECTIONS[self.section]),
        };
        if self.screen == Screen::Section && SECTIONS[self.section] == "Shell" {
            rows.push((String::new(), String::new()));
            rows.push((
                "# The toolbelt".into(),
                "tldr NAME for examples (works offline)".into(),
            ));
            for (group, tools) in TOOLBELT {
                rows.push((format!("# {group}"), String::new()));
                rows.extend(tools.iter().map(|(t, w)| (t.to_string(), w.to_string())));
            }
        }
        self.overlays.push(Overlay::Keys {
            title,
            rows,
            scroll: 0,
        });
    }

    fn quit(&self) -> Effect {
        Effect::Quit(if self.live() {
            Some("shell".into())
        } else {
            None
        })
    }

    /// Home: the tiles in a grid of three a row, the suggestion line above them.
    fn home_key(&mut self, k: KeyEvent) -> Vec<Effect> {
        let n = SECTIONS.len();
        let cols = self.home_cols();
        let sugg = self.suggestions().len();
        match (self.home, k.code) {
            (_, KeyCode::Char(c @ '1'..='7')) => {
                return self.open_section((c as usize) - ('1' as usize));
            }
            (_, KeyCode::Char('f')) if sugg > 0 => return self.suggestion(0),
            (HomeSel::Tile(t), KeyCode::Right | KeyCode::Tab) => {
                self.home = HomeSel::Tile((t + 1) % n)
            }
            (HomeSel::Tile(t), KeyCode::Left) => self.home = HomeSel::Tile((t + n - 1) % n),
            (HomeSel::Tile(t), KeyCode::Down | KeyCode::Char('j')) => {
                self.home = HomeSel::Tile(if t + cols < n {
                    t + cols
                } else if cols == n {
                    (t + 1) % n
                } else {
                    t
                })
            }
            (HomeSel::Tile(t), KeyCode::Up | KeyCode::Char('k')) => {
                self.home = if t >= cols {
                    HomeSel::Tile(t - cols)
                } else if sugg > 0 {
                    HomeSel::Suggestion(0)
                } else if cols == n {
                    HomeSel::Tile((t + n - 1) % n)
                } else {
                    HomeSel::Tile(t)
                }
            }
            (HomeSel::Tile(t), KeyCode::Enter) => return self.open_section(t),
            (
                HomeSel::Suggestion(_),
                KeyCode::Down | KeyCode::Char('j') | KeyCode::Tab | KeyCode::Esc,
            ) => self.home = HomeSel::Tile(0),
            (HomeSel::Suggestion(i), KeyCode::Enter) => return self.suggestion(i),
            (_, KeyCode::Char('q') | KeyCode::Esc) => return vec![self.quit()],
            _ => {}
        }
        vec![]
    }

    fn section_key(&mut self, k: KeyEvent) -> Vec<Effect> {
        let n = self.items().len();
        if SECTIONS[self.section] == "Tools" && n > 0 {
            match k.code {
                KeyCode::Right => {
                    self.sel = (self.sel + 1) % n;
                    return vec![];
                }
                KeyCode::Left => {
                    self.sel = (self.sel + n - 1) % n;
                    return vec![];
                }
                KeyCode::Down | KeyCode::Char('j') => {
                    self.sel = (self.sel + tool_cols(self.size.width)).min(n - 1);
                    return vec![];
                }
                KeyCode::Up | KeyCode::Char('k') => {
                    self.sel = self.sel.saturating_sub(tool_cols(self.size.width));
                    return vec![];
                }
                _ => {}
            }
        }
        match k.code {
            KeyCode::Up | KeyCode::Char('k') if n > 0 => self.sel = (self.sel + n - 1) % n,
            KeyCode::Down | KeyCode::Char('j') | KeyCode::Tab if n > 0 => {
                self.sel = (self.sel + 1) % n
            }
            KeyCode::Enter => {
                if let Some(i) = self.items().get(self.sel).cloned() {
                    return self.choose(&i);
                }
            }
            KeyCode::Esc
            | KeyCode::Backspace
            | KeyCode::Left
            | KeyCode::Char('h')
            | KeyCode::Char('q') => {
                self.screen = Screen::Home;
                self.home = HomeSel::Tile(self.section);
            }
            _ => {}
        }
        vec![]
    }

    /// The pointer moved: on Home, the tile under it (for the hint bar).
    pub fn hover(&mut self, col: u16, row: u16) {
        let at = ratatui::layout::Position::new(col, row);
        self.hover = (self.screen == Screen::Home)
            .then(|| {
                home_layout(self, self.size)
                    .tiles
                    .iter()
                    .position(|r| r.contains(at))
            })
            .flatten();
    }

    /// A mouse click: on Home a tile opens; in a section an item is chosen.
    pub fn click(&mut self, col: u16, row: u16) -> Vec<Effect> {
        if !self.overlays.is_empty() {
            return vec![];
        }
        let at = ratatui::layout::Position::new(col, row);
        match self.screen {
            Screen::Home => {
                let l = home_layout(self, self.size);
                if let Some(t) = l.tiles.iter().position(|r| r.contains(at)) {
                    return self.open_section(t);
                } else if let Some(r) = l.suggest
                    && r.contains(at)
                    && !self.suggestions().is_empty()
                {
                    return self.suggestion(0);
                }
                vec![]
            }
            Screen::Section => {
                if let Some(i) = item_at(self, self.size, at) {
                    self.sel = i;
                    if let Some(it) = self.items().get(i).cloned() {
                        return self.choose(&it);
                    }
                }
                vec![]
            }
        }
    }

    /// An item chosen.
    pub fn choose(&mut self, i: &Item) -> Vec<Effect> {
        let why = self.blocked(i);
        match i.need {
            // it needs the install open: open it right here (the same steps as Mount my
            // bromigOS install), then choose it again
            Need::Mounted if !why.is_empty() => {
                return self.call("Looking for installs", Then::Installs, &["installs"]);
            }
            Need::Internet if !why.is_empty() => {
                self.message(i.label, "This needs the internet, and this machine isn't online. Connect in Lab › Network settings, then try again. Everything else in Field Kit works without it.", false);
                return vec![];
            }
            Need::Lan if !why.is_empty() => {
                self.message(i.label, "This talks to the other machines in your lab over your local network, and this machine has no network link. Plug in a cable or join Wi-Fi in Lab › Network settings. (The internet isn't needed.)", false);
                return vec![];
            }
            _ => {}
        }
        match &i.act {
            Act::Mount => self.call("Looking for installs", Then::Installs, &["installs"]),
            Act::Unmount => self.call(
                "Unmounting",
                Then::Message("Unmount my install".into()),
                &["unmount"],
            ),
            Act::Why => self.call(
                "Reading its log",
                Then::Findings {
                    title: i.label.into(),
                    check: "last-boot".into(),
                },
                &["check", "last-boot"],
            ),
            Act::Black => self.call(
                "Checking",
                Then::Findings {
                    title: i.label.into(),
                    check: "black-screen".into(),
                },
                &["check", "black-screen"],
            ),
            Act::Rollback => self.call("Reading the snapshots", Then::Snapshots, &["snapshots"]),
            Act::Grub => {
                self.overlays.push(Overlay::Confirm {
                    question: "Put GRUB back and make the boot menu again?".into(),
                    detail: format!("For a machine that goes straight to the firmware, or a boot menu that's missing or broken. The old menu is kept in a backup.\n\nIt touches: {}.", act_touches(&Act::Grub)),
                    yes: "Repair it".into(),
                    sel: 0,
                    then: Pick::GrubYes,
                });
                vec![]
            }
            Act::BootOptions => self.call(
                "Reading the boot options",
                Then::BootOptions,
                &["boot-options"],
            ),
            Act::Edit => self.call(
                "Finding the usual files",
                Then::EditCandidates,
                &["edit-candidates"],
            ),
            Act::Disks => self.call("Asking the drives", Then::Disks, &["disks"]),
            Act::Backup => self.call(
                "Looking for USB drives",
                Then::BackupTargets,
                &["backup-targets"],
            ),
            Act::Image => {
                self.overlays.push(Overlay::Pick {
                    title: "Copy or image a disk".into(),
                    options: vec![
                        (
                            "create".into(),
                            "Make an image of a disk or partition · to a USB drive or a share"
                                .into(),
                        ),
                        (
                            "restore".into(),
                            "Restore an image · Field Kit's, Clonezilla's or Rescuezilla's".into(),
                        ),
                        (
                            "clone".into(),
                            "Copy a disk onto another disk · everything on the other is replaced"
                                .into(),
                        ),
                        (
                            "verify".into(),
                            "Check an image · reads it back against its checksums".into(),
                        ),
                    ],
                    sel: 0,
                    then: Pick::ImageAction,
                });
                vec![]
            }
            Act::Erase => self.call("Asking the drives", Then::DiskPick(Flow::Erase), &["disks"]),
            Act::Windows => self.call(
                "Looking for Windows",
                Then::WindowsFind,
                &["windows", "find"],
            ),
            Act::Graphics => self.call("Looking at the graphics", Then::Graphics, &["graphics"]),
            Act::Remote => {
                let on = self.status["remote"]["on"].as_bool().unwrap_or(false);
                self.overlays.push(Overlay::Confirm {
                    question: if on { "Turn remote help off?".into() } else { "Turn remote help on?".into() },
                    detail: if on {
                        "SSH stops, and the one-time password stops working.".into()
                    } else {
                        "SSH starts so someone can sign in and help. With a key on your Field Kit stick, only that key works; without one, a one-time password is shown here. The status line says REMOTE HELP ON while it's on.".into()
                    },
                    yes: if on { "Turn it off".into() } else { "Turn it on".into() },
                    sel: 0,
                    then: Pick::RemoteToggle(!on),
                });
                vec![]
            }
            Act::MakeStick => vec![Effect::Exec(vec![engine_path(), "make-stick".into()])],
            Act::Tool(argv) => vec![Effect::Exec(argv.iter().map(|s| s.to_string()).collect())],
            Act::Card(_, _, argv) => {
                vec![Effect::Exec(argv.iter().map(|s| s.to_string()).collect())]
            }
            Act::Manual => vec![Effect::Exec(args(&[
                "lynx",
                "-nopause",
                "/usr/share/doc/bromigos/manual/index.html",
            ]))],
            // bromigos-iso-install's text installer: its own edition and disk steps (the edition
            // preselected from bromigos.edition= on the kernel line: Server on the Field Kit stick)
            Act::InstallEdition(_) => vec![Effect::Exec(vec![installer(), "--text".into()])],
            Act::Shell => vec![Effect::Exec(vec![
                std::env::var("SHELL").unwrap_or_else(|_| "/bin/bash".into()),
                "-l".into(),
            ])],
            Act::Chroot => {
                let root = self.target().map(|t| s(t, "root")).unwrap_or_default();
                if root.is_empty() || root == "/" {
                    vec![Effect::Exec(vec![
                        std::env::var("SHELL").unwrap_or_else(|_| "/bin/bash".into()),
                        "-l".into(),
                    ])]
                } else {
                    vec![Effect::Exec(vec!["arch-chroot".into(), root])]
                }
            }
            Act::PairBrodec => vec![Effect::Pair],
            Act::AboutServer => {
                self.message(
                    "What bromigOS Server is",
                    "bromigOS Server is bromigOS without the desktop, for servers and lab machines. It starts to this console, in the same colours, with Field Kit's tools on it.\n\nWhat it runs: SSH (with your key, if you turned it on), a firewall that lets only SSH in until you open more, Podman for containers, the lab's monitoring, and herdr.\n\nHow it looks after itself: security updates install on their own, each after a snapshot; if the server doesn't come back healthy, it rolls itself back to that snapshot.\n\nInstall it from Install › bromigOS Server: everything it needs is on this stick, so no network is needed.",
                    false,
                );
                vec![]
            }
            Act::ServerUpdate => vec![Effect::Exec(vec![
                SERVER_STATUS.into(),
                "update".into(),
                "--now".into(),
            ])],
            Act::Firewall(what, set) => vec![Effect::Exec(vec![
                SERVER_STATUS.into(),
                "firewall".into(),
                what.to_string(),
                set.to_string(),
            ])],
            Act::ServerSsh => {
                // keys only: the SSH settings decide passwords; this only starts or stops it
                let on = self.server["ssh"]
                    .as_bool()
                    .or(self.overview["ssh"]["on"].as_bool())
                    .unwrap_or(false);
                vec![Effect::Exec(args(&[
                    "systemctl",
                    if on { "disable" } else { "enable" },
                    "--now",
                    "sshd.service",
                ]))]
            }
            Act::Containers => vec![Effect::Exec(args(&[
                "sh",
                "-c",
                "podman ps --all; echo; read -r -p 'ENTER goes back ' _",
            ]))],
            Act::Cluster => {
                self.message(
                    "Join the lab's cluster",
                    "Your lab adds this server as a node: on the computer with your lab's settings, run bromigos lab provision add-node, and name this server. It's joined over SSH, with your key, and checked before anything changes.",
                    false,
                );
                vec![]
            }
            Act::Power(p) => {
                self.overlays.push(Overlay::Confirm {
                    question: format!("{} now?", i.label),
                    detail: if self.mounted_by_us() {
                        "Your install is unmounted and locked first.".into()
                    } else {
                        String::new()
                    },
                    yes: i.label.into(),
                    sel: 0,
                    then: Pick::Power(p.to_string()),
                });
                vec![]
            }
        }
    }

    fn overlay_key(&mut self, k: KeyEvent) -> Vec<Effect> {
        let Some(top) = self.overlays.last_mut() else {
            return vec![];
        };
        let esc = k.code == KeyCode::Esc;
        match top {
            Overlay::Busy { .. } => vec![],
            Overlay::Commands {
                title,
                commands,
                touches,
                cli,
                note,
                sel,
            } => {
                match k.code {
                    KeyCode::Left | KeyCode::BackTab => *sel = (*sel + 2) % 3,
                    KeyCode::Right | KeyCode::Tab => *sel = (*sel + 1) % 3,
                    KeyCode::Esc | KeyCode::Char('q') => {
                        self.overlays.pop();
                    }
                    KeyCode::Enter => match *sel {
                        0 => {
                            let text = if commands.is_empty() {
                                cli.clone()
                            } else {
                                commands.join("\n")
                            };
                            *note = "Copied, if this terminal takes it (OSC 52): desktop terminals, kmscon and most SSH apps do; the Linux console and some multiplexers don't.".into();
                            return vec![Effect::Copy(text)];
                        }
                        1 => {
                            let (t, c, to, cl) = (
                                title.clone(),
                                commands.clone(),
                                touches.clone(),
                                cli.clone(),
                            );
                            if c.is_empty() {
                                *note = "There's nothing to run step by step here.".into();
                                return vec![];
                            }
                            return match self.steps(&t, &c, &to, &cl) {
                                Ok(e) => vec![e],
                                Err(e) => {
                                    self.message(
                                        "Run step by step",
                                        &format!("The steps file couldn't be written: {e}"),
                                        false,
                                    );
                                    vec![]
                                }
                            };
                        }
                        _ => {
                            self.overlays.pop();
                        }
                    },
                    _ => {}
                }
                vec![]
            }
            Overlay::Keys { scroll, rows, .. } => {
                match k.code {
                    KeyCode::Down | KeyCode::Char('j') => {
                        *scroll = (*scroll + 1).min(rows.len().saturating_sub(1))
                    }
                    KeyCode::Up | KeyCode::Char('k') => *scroll = scroll.saturating_sub(1),
                    KeyCode::PageDown | KeyCode::Char(' ') => {
                        *scroll = (*scroll + 10).min(rows.len().saturating_sub(1))
                    }
                    KeyCode::PageUp => *scroll = scroll.saturating_sub(10),
                    _ => {}
                }
                if matches!(
                    k.code,
                    KeyCode::Enter
                        | KeyCode::Esc
                        | KeyCode::Char('q')
                        | KeyCode::Char('?')
                        | KeyCode::F(1)
                ) {
                    self.overlays.pop();
                }
                vec![]
            }
            Overlay::Message { .. } => {
                if matches!(
                    k.code,
                    KeyCode::Enter | KeyCode::Esc | KeyCode::Char(' ') | KeyCode::Char('q')
                ) {
                    self.overlays.pop();
                    if self.overlays.is_empty() {
                        return vec![Effect::Call {
                            then: Then::Status,
                            args: args(&["status"]),
                            stdin: None,
                        }];
                    }
                }
                vec![]
            }
            Overlay::Progress { done, .. } => {
                if done.is_some()
                    && matches!(k.code, KeyCode::Enter | KeyCode::Esc | KeyCode::Char('q'))
                {
                    self.overlays.pop();
                }
                vec![]
            }
            Overlay::Findings {
                items, sel, check, ..
            } => {
                let fixable: Vec<usize> = (0..items.len())
                    .filter(|i| {
                        !items[*i].fix.is_empty() && !items[*i].ok && items[*i].result.is_empty()
                    })
                    .collect();
                match k.code {
                    KeyCode::Esc | KeyCode::Char('q') => {
                        self.overlays.pop();
                    }
                    KeyCode::Up | KeyCode::Char('k') if !fixable.is_empty() => {
                        let pos = fixable.iter().position(|i| i == sel).unwrap_or(0);
                        *sel = fixable[(pos + fixable.len() - 1) % fixable.len()];
                    }
                    KeyCode::Down | KeyCode::Char('j') | KeyCode::Tab if !fixable.is_empty() => {
                        let pos = fixable
                            .iter()
                            .position(|i| i == sel)
                            .map(|p| p + 1)
                            .unwrap_or(0);
                        *sel = fixable[pos % fixable.len()];
                    }
                    KeyCode::Enter => {
                        if fixable.contains(sel) {
                            let id = items[*sel].id.clone();
                            items[*sel].result = "working…".into();
                            let check = check.clone();
                            return vec![Effect::Call {
                                then: Then::Fixed {
                                    check: check.clone(),
                                    id: id.clone(),
                                },
                                args: vec!["fix".into(), check, id],
                                stdin: None,
                            }];
                        }
                        self.overlays.pop();
                    }
                    _ => {}
                }
                vec![]
            }
            Overlay::Pick {
                options, sel, then, ..
            } => {
                let n = options.len();
                match k.code {
                    KeyCode::Esc => {
                        self.overlays.pop();
                    }
                    KeyCode::Up | KeyCode::Char('k') if n > 0 => *sel = (*sel + n - 1) % n,
                    KeyCode::Down | KeyCode::Char('j') if n > 0 => *sel = (*sel + 1) % n,
                    KeyCode::Enter if n > 0 => {
                        let id = options[*sel].0.clone();
                        let then = then.clone();
                        self.overlays.pop();
                        return self.picked(then, id);
                    }
                    _ => {}
                }
                vec![]
            }
            Overlay::Input { value, then, .. } => {
                match k.code {
                    KeyCode::Esc => {
                        self.overlays.pop();
                    }
                    KeyCode::Backspace => {
                        value.pop();
                    }
                    KeyCode::Char(c) if !k.modifiers.contains(KeyModifiers::CONTROL) => {
                        value.push(c)
                    }
                    KeyCode::Enter => {
                        let (then, v) = (then.clone(), value.clone());
                        self.overlays.pop();
                        return self.picked(then, v);
                    }
                    _ => {}
                }
                vec![]
            }
            Overlay::Confirm { sel, then, .. } => {
                let n = confirm_labels("", then).len();
                match k.code {
                    KeyCode::Right | KeyCode::Tab => *sel = (*sel + 1) % n,
                    KeyCode::Left | KeyCode::BackTab => *sel = (*sel + n - 1) % n,
                    KeyCode::Esc => {
                        self.overlays.pop();
                    }
                    KeyCode::Enter => {
                        let (choice, then) = (*sel, then.clone());
                        if n == 3 && choice == 1 {
                            return self.commands_here().unwrap_or_default();
                        }
                        self.overlays.pop();
                        if choice == 0 {
                            return self.picked(then, "yes".into());
                        }
                    }
                    _ => {}
                }
                vec![]
            }
            Overlay::Typed {
                want, typed, then, ..
            } => {
                match k.code {
                    _ if esc => {
                        self.overlays.pop();
                    }
                    KeyCode::Backspace => {
                        typed.pop();
                    }
                    KeyCode::Char(c) if !k.modifiers.contains(KeyModifiers::CONTROL) => {
                        typed.push(c)
                    }
                    KeyCode::Enter if widgets::typed_ok(want, typed) => {
                        let (then, v) = (then.clone(), typed.trim().to_string());
                        self.overlays.pop();
                        return self.picked(then, v);
                    }
                    _ => {}
                }
                vec![]
            }
            Overlay::BootOptions {
                words,
                presets,
                on,
                sel,
                other,
            } => {
                let n = presets.len() + 1;
                match k.code {
                    KeyCode::Esc => {
                        self.overlays.pop();
                    }
                    KeyCode::Up => *sel = (*sel + n) % (n + 1),
                    KeyCode::Down | KeyCode::Tab => *sel = (*sel + 1) % (n + 1),
                    KeyCode::Char(' ') if *sel < presets.len() => on[*sel] = !on[*sel],
                    KeyCode::Char(c) if *sel == presets.len() => other.push(c),
                    KeyCode::Backspace if *sel == presets.len() => {
                        other.pop();
                    }
                    KeyCode::Enter if *sel < presets.len() => on[*sel] = !on[*sel],
                    KeyCode::Enter => {
                        let mut new: Vec<String> = presets
                            .iter()
                            .zip(on.iter())
                            .filter(|(_, o)| **o)
                            .map(|(p, _)| p.0.clone())
                            .collect();
                        new.extend(other.split_whitespace().map(String::from));
                        let mut seen = std::collections::HashSet::new();
                        new.retain(|w| seen.insert(w.clone()));
                        let _ = words;
                        self.overlays.pop();
                        let mut a = vec!["boot-options".to_string(), "--set".to_string()];
                        a.extend(new);
                        self.busy("Saving and making the boot menu again");
                        return vec![Effect::Call {
                            then: Then::Message("Change the boot options".into()),
                            args: a,
                            stdin: None,
                        }];
                    }
                    _ => {}
                }
                vec![]
            }
        }
    }

    /// A choice made in a dialog.
    fn picked(&mut self, then: Pick, v: String) -> Vec<Effect> {
        match then {
            Pick::MountDevice => {
                let enc = v.starts_with("enc:");
                let dev = v.trim_start_matches("enc:").to_string();
                if enc {
                    self.overlays.push(Overlay::Input {
                        title: format!("Unlock {dev}"),
                        prompt: "Type the passphrase you type at startup.".into(),
                        value: String::new(),
                        hidden: true,
                        then: Pick::Passphrase(dev),
                    });
                    vec![]
                } else {
                    self.busy("Mounting");
                    vec![Effect::Call {
                        then: Then::Mounted,
                        args: vec!["mount".into(), dev],
                        stdin: None,
                    }]
                }
            }
            Pick::Passphrase(dev) => {
                self.busy("Unlocking");
                vec![Effect::Call {
                    then: Then::Mounted,
                    args: vec!["mount".into(), dev],
                    stdin: Some(v),
                }]
            }
            Pick::Snapshot => {
                self.overlays.push(Overlay::Confirm {
                    question: format!("Start from snapshot {v} from now on?"),
                    detail: format!("The system as it is now is kept beside it, so this can be undone. Your files in /home aren't touched.\n\nIt touches: {}.", act_touches(&Act::Rollback)),
                    yes: "Roll back".into(),
                    sel: 0,
                    then: Pick::RollbackYes(v),
                });
                vec![]
            }
            Pick::RollbackYes(n) => {
                self.busy("Rolling back");
                vec![Effect::Call {
                    then: Then::Message("Roll back to a snapshot".into()),
                    args: vec!["rollback".into(), n],
                    stdin: None,
                }]
            }
            Pick::GrubYes => self.call(
                "Repairing the boot menu",
                Then::Message("Repair the boot menu".into()),
                &["grub-repair"],
            ),
            Pick::EditFile => {
                if v == "__typed__" {
                    self.overlays.push(Overlay::Input {
                        title: "Edit a file on my install".into(),
                        prompt: "The file's path inside the install, for example /etc/environment."
                            .into(),
                        value: String::new(),
                        hidden: false,
                        then: Pick::EditTyped,
                    });
                    return vec![];
                }
                self.busy("Backing it up");
                vec![Effect::Call {
                    then: Then::EditOpen,
                    args: vec!["edit-prepare".into(), v],
                    stdin: None,
                }]
            }
            Pick::EditTyped => {
                if v.trim().is_empty() {
                    return vec![];
                }
                self.busy("Backing it up");
                vec![Effect::Call {
                    then: Then::EditOpen,
                    args: vec!["edit-prepare".into(), v.trim().to_string()],
                    stdin: None,
                }]
            }
            Pick::BackupDrive => {
                self.overlays.push(Overlay::Progress {
                    title: "Back up my files to a USB drive".into(),
                    lines: vec![],
                    pct: None,
                    done: None,
                });
                vec![Effect::Stream {
                    then: Then::Message("Back up my files to a USB drive".into()),
                    args: vec!["backup".into(), v],
                }]
            }
            Pick::ImageAction => match v.as_str() {
                "restore" | "verify" => self.call(
                    "Looking for images",
                    Then::ImageList(v.clone()),
                    &["image", "list"],
                ),
                _ => self.call(
                    "Asking the drives",
                    Then::DiskPick(Flow::ImageSource(v.clone())),
                    &["disks"],
                ),
            },
            Pick::ImageSource(action) => {
                if action == "clone" {
                    return self.call(
                        "Asking the drives",
                        Then::DiskPick(Flow::ImageTarget { action, from: v }),
                        &["disks"],
                    );
                }
                self.call(
                    "Looking for where it can go",
                    Then::ImageTargets(v),
                    &["image", "targets"],
                )
            }
            Pick::ImageDest(source) => {
                if v == "__share__" {
                    self.overlays.push(Overlay::Input {
                        title: "A share on your local network".into(),
                        prompt: "Its address: smb://host/share for Windows and Samba shares, nfs://host/path for NFS. Your local network is enough; no internet needed.".into(),
                        value: String::new(),
                        hidden: false,
                        then: Pick::ShareUrl(source),
                    });
                    return vec![];
                }
                self.image_create(source, v)
            }
            Pick::ShareUrl(source) => {
                let url = v.trim().to_string();
                if url.is_empty() {
                    return vec![];
                }
                if url.starts_with("nfs://") {
                    self.busy("Connecting to the share");
                    return vec![Effect::Call {
                        then: Then::ShareMounted(source),
                        args: vec!["image".into(), "mount-share".into(), url],
                        stdin: None,
                    }];
                }
                self.overlays.push(Overlay::Input {
                    title: "Sign in to the share".into(),
                    prompt: "Its user name (leave it empty for a share anyone can write to)."
                        .into(),
                    value: String::new(),
                    hidden: false,
                    then: Pick::ShareUser { source, url },
                });
                vec![]
            }
            Pick::ShareUser { source, url } => {
                let user = v.trim().to_string();
                if user.is_empty() {
                    self.busy("Connecting to the share");
                    return vec![Effect::Call {
                        then: Then::ShareMounted(source),
                        args: vec!["image".into(), "mount-share".into(), url],
                        stdin: None,
                    }];
                }
                self.overlays.push(Overlay::Input {
                    title: "Sign in to the share".into(),
                    prompt: format!("{user}'s password on the share."),
                    value: String::new(),
                    hidden: true,
                    then: Pick::SharePass { source, url, user },
                });
                vec![]
            }
            Pick::SharePass { source, url, user } => {
                self.busy("Connecting to the share");
                vec![Effect::Call {
                    then: Then::ShareMounted(source),
                    args: vec![
                        "image".into(),
                        "mount-share".into(),
                        url,
                        "--user".into(),
                        user,
                    ],
                    stdin: Some(v),
                }]
            }
            Pick::ImageChosen(action) => {
                if action == "verify" {
                    self.overlays.push(Overlay::Progress {
                        title: "Check an image".into(),
                        lines: vec![],
                        pct: None,
                        done: None,
                    });
                    return vec![Effect::Stream {
                        then: Then::Message("Check an image".into()),
                        args: vec!["image".into(), "verify".into(), v],
                    }];
                }
                self.call(
                    "Asking the drives",
                    Then::DiskPick(Flow::ImageTarget { action, from: v }),
                    &["disks"],
                )
            }
            Pick::ImageTarget { action, from } => {
                let name = dev_name(&v);
                let what = if action == "restore" {
                    "Restore an image"
                } else {
                    "Copy a disk"
                };
                self.overlays.push(Overlay::Typed {
                    question: format!("Replace everything on {v}?"),
                    detail: format!(
                        "{what}: everything now on {v} is replaced by {from}, and can't be brought back."
                    ),
                    want: name,
                    typed: String::new(),
                    then: Pick::ImageTyped { action, from, target: v },
                });
                vec![]
            }
            Pick::ImageTyped {
                action,
                from,
                target,
            } => {
                let title = if action == "restore" {
                    "Restore an image"
                } else {
                    "Copy a disk"
                };
                self.overlays.push(Overlay::Progress {
                    title: title.into(),
                    lines: vec![],
                    pct: None,
                    done: None,
                });
                let src = if action == "restore" {
                    "--image"
                } else {
                    "--source"
                };
                vec![Effect::Stream {
                    then: Then::Message(title.into()),
                    args: vec![
                        "image".into(),
                        action,
                        src.into(),
                        from,
                        "--target".into(),
                        target,
                        "--confirm".into(),
                        v,
                    ],
                }]
            }
            Pick::EraseDisk => {
                self.busy("Checking what this drive can do");
                vec![Effect::Call {
                    then: Then::ErasePlan(v.clone()),
                    args: vec!["erase".into(), "plan".into(), v],
                    stdin: None,
                }]
            }
            Pick::EraseMethod { dev, name, detail } => {
                self.overlays.push(Overlay::Typed {
                    question: format!("Erase {dev} for good?"),
                    detail: format!(
                        "{detail}\n\nEverything on it is destroyed and can't be brought back. A report is saved to the Field Kit stick."
                    ),
                    want: name,
                    typed: String::new(),
                    then: Pick::EraseTyped { dev, method: v },
                });
                vec![]
            }
            Pick::EraseTyped { dev, method } => {
                self.overlays.push(Overlay::Progress {
                    title: format!("Erasing {dev}"),
                    lines: vec![],
                    pct: None,
                    done: None,
                });
                vec![Effect::Stream {
                    then: Then::Message("Erase a disk securely".into()),
                    args: vec![
                        "erase".into(),
                        "run".into(),
                        dev,
                        "--confirm".into(),
                        v,
                        "--method".into(),
                        method,
                    ],
                }]
            }
            Pick::WindowsAction => {
                let (what, part) = v.split_once(':').unwrap_or((v.as_str(), ""));
                let part = part.to_string();
                match what {
                    "pw" => self.call(
                        "Reading the accounts",
                        Then::WindowsUsers(part.clone()),
                        &["windows", "users", "--part", &part],
                    ),
                    "fix" => self.call(
                        "Fixing NTFS",
                        Then::Message("Fix NTFS".into()),
                        &["windows", "ntfsfix", "--part", &part],
                    ),
                    "bl" => {
                        self.overlays.push(Overlay::Input {
                            title: "Open a BitLocker drive".into(),
                            prompt: "Type its 48-digit recovery key (with or without the dashes). You'll find it in the Microsoft account the PC was set up with, or printed where it was saved.".into(),
                            value: String::new(),
                            hidden: false,
                            then: Pick::WindowsKey(part),
                        });
                        vec![]
                    }
                    "lock" => self.call(
                        "Closing it",
                        Then::Message("Close a BitLocker drive".into()),
                        &["windows", "lock-bitlocker", "--part", &part],
                    ),
                    _ => self.call(
                        "Reading the boot entries",
                        Then::BootEntries,
                        &["windows", "boot-entries"],
                    ),
                }
            }
            Pick::WindowsUser { part, warning } => {
                self.overlays.push(Overlay::Confirm {
                    question: format!("Reset {v}'s password?"),
                    detail: if warning.is_empty() {
                        format!("{v} gets an empty password: sign in to Windows without one, then set a new one there.")
                    } else {
                        warning
                    },
                    yes: "Reset it".into(),
                    sel: 1,
                    then: Pick::WindowsResetYes { part, user: v },
                });
                vec![]
            }
            Pick::WindowsResetYes { part, user } => self.call(
                "Resetting the password",
                Then::Message("Reset a Windows password".into()),
                &[
                    "windows",
                    "reset-password",
                    "--part",
                    &part,
                    "--user",
                    &user,
                ],
            ),
            Pick::WindowsKey(part) => {
                self.busy("Opening it");
                vec![Effect::Call {
                    then: Then::Message("Open a BitLocker drive".into()),
                    args: vec![
                        "windows".into(),
                        "unlock-bitlocker".into(),
                        "--part".into(),
                        part,
                    ],
                    stdin: Some(v),
                }]
            }
            Pick::BootFix => {
                let mut a = vec!["windows", "boot-fix"];
                match v.as_str() {
                    "readd" => a.push("--readd"),
                    "windows" => a.extend(["--first", "windows"]),
                    _ => a.extend(["--first", "bromigos"]),
                }
                self.call(
                    "Changing the boot entries",
                    Then::Message("Repair Windows' boot entry".into()),
                    &a,
                )
            }
            Pick::Power(p) => vec![Effect::Quit(Some(p))],
            Pick::RemoteToggle(on) => self.call(
                "Remote help",
                Then::Remote,
                &["remote", if on { "on" } else { "off" }],
            ),
        }
    }

    // -------------------------------------------------------------- the engine's replies

    /// Progress from a streaming job.
    pub fn progress(&mut self, pct: Option<u8>, line: String) {
        if let Some(Overlay::Progress { lines, pct: p, .. }) = self.overlays.last_mut() {
            if pct.is_some() {
                *p = pct;
            }
            if !line.is_empty() {
                lines.push(line);
                if lines.len() > 2000 {
                    lines.drain(..1000);
                }
            }
        }
    }

    /// The engine answered.
    pub fn reply(&mut self, then: Then, v: Value) -> Vec<Effect> {
        let ok = v["ok"].as_bool().unwrap_or(false);
        let msg = s(&v, "message");
        // where a job left something: an erase's report, an image's folder
        let msg = match (s(&v, "report"), s(&v, "path")) {
            (r, _) if !r.is_empty() && !msg.contains(&r) => format!("{msg}\nThe report is in {r}."),
            (_, p) if !p.is_empty() && v.get("verified").is_some() && !msg.contains(&p) => {
                format!("{msg}\nThe image is in {p}.")
            }
            _ => msg,
        };
        // a streaming job's end: its panel stays, with the outcome
        if let Some(Overlay::Progress { done, .. }) = self.overlays.last_mut()
            && done.is_none()
            && !matches!(
                then,
                Then::Status | Then::Overview | Then::DisksQuiet | Then::SnapshotsQuiet
            )
        {
            *done = Some((ok, if msg.is_empty() { "Done.".into() } else { msg }));
            if ok {
                self.spark();
            }
            return vec![];
        }
        if !matches!(
            then,
            Then::Status
                | Then::Overview
                | Then::DisksQuiet
                | Then::SnapshotsQuiet
                | Then::Fixed { .. }
        ) && let Some(Overlay::Busy { .. }) = self.overlays.last()
        {
            self.overlays.pop();
        }
        if !ok
            && !matches!(
                then,
                Then::Status
                    | Then::Overview
                    | Then::DisksQuiet
                    | Then::SnapshotsQuiet
                    | Then::Fixed { .. }
            )
        {
            let title = match &then {
                Then::Message(t) => t.clone(),
                Then::Findings { title, .. } => title.clone(),
                _ => "Field Kit".into(),
            };
            let text = if msg.is_empty() {
                "That isn't on this Field Kit yet.".to_string()
            } else {
                msg
            };
            self.message(&title, &text, false);
            return vec![];
        }
        match then {
            Then::DisksQuiet => {
                self.disks = v;
            }
            Then::SnapshotsQuiet => {
                self.snap_count = v["snapshots"].as_array().map(Vec::len);
            }
            Then::Plan { title, cli } => {
                self.overlays.push(Overlay::Commands {
                    title,
                    commands: strings(&v["commands"]),
                    touches: strings(&v["touches"]),
                    cli,
                    note: String::new(),
                    sel: 0,
                });
            }
            Then::Overview => {
                if v.is_object() {
                    self.keep_temps(&v);
                    self.overview = v;
                    let n = self.suggestions().len();
                    if let HomeSel::Suggestion(i) = self.home
                        && i >= n
                    {
                        self.home = HomeSel::Tile(0);
                    }
                }
            }
            Then::Status => {
                if v.is_object() {
                    self.status = v;
                }
            }
            Then::Message(title) => {
                let extra = s(&v, "warning");
                let text = if extra.is_empty() {
                    msg
                } else {
                    format!("{msg}\n\n{extra}")
                };
                self.message(&title, &text, true);
                return vec![Effect::Call {
                    then: Then::Status,
                    args: args(&["status"]),
                    stdin: None,
                }];
            }
            Then::Mounted => {
                let extra = s(&v, "warning");
                self.message(
                    "Mounted",
                    &if extra.is_empty() {
                        msg
                    } else {
                        format!("{msg}\n\n{extra}")
                    },
                    true,
                );
                return vec![Effect::Call {
                    then: Then::Status,
                    args: args(&["status"]),
                    stdin: None,
                }];
            }
            Then::Installs => {
                let list = v["installs"].as_array().cloned().unwrap_or_default();
                if list.is_empty() {
                    self.message("Mount my bromigOS install", "Field Kit found no bromigOS install on this machine's drives (no encrypted or btrfs partition). If it's on a drive that isn't connected, connect it and try again.", false);
                } else {
                    let options = list
                        .iter()
                        .map(|p| {
                            let enc = p["encrypted"].as_bool().unwrap_or(false);
                            let id = if enc {
                                format!("enc:{}", s(p, "path"))
                            } else {
                                s(p, "path")
                            };
                            let mut words = vec![s(p, "path"), s(p, "size")];
                            for k in ["label", "model"] {
                                if !s(p, k).is_empty() {
                                    words.push(s(p, k));
                                }
                            }
                            words.push(if enc {
                                "encrypted".into()
                            } else {
                                "btrfs".into()
                            });
                            (id, words.join(" · "))
                        })
                        .collect();
                    self.overlays.push(Overlay::Pick {
                        title: "Which install?".into(),
                        options,
                        sel: 0,
                        then: Pick::MountDevice,
                    });
                }
            }
            Then::Findings { title, check } => {
                let items = findings(&v);
                if check == "black-screen" {
                    self.black_count = Some(items.iter().filter(|f| !f.ok).count());
                }
                let sel = items
                    .iter()
                    .position(|f| !f.fix.is_empty() && !f.ok)
                    .unwrap_or(0);
                self.overlays.push(Overlay::Findings {
                    title,
                    check,
                    items,
                    sel,
                });
            }
            Then::Fixed { id, .. } => {
                if let Some(Overlay::Findings { items, sel, .. }) = self.overlays.last_mut() {
                    if let Some(f) = items.iter_mut().find(|f| f.id == id) {
                        f.result = if msg.is_empty() { "done".into() } else { msg };
                        f.fixed_at = ok.then(Instant::now);
                    }
                    if let Some(next) = (0..items.len()).find(|i| {
                        !items[*i].fix.is_empty() && !items[*i].ok && items[*i].result.is_empty()
                    }) {
                        *sel = next;
                    }
                }
                if ok {
                    self.spark();
                }
            }
            Then::Snapshots => {
                let list = v["snapshots"].as_array().cloned().unwrap_or_default();
                if list.is_empty() {
                    self.message(
                        "Roll back to a snapshot",
                        "This install has no snapshots to go back to.",
                        false,
                    );
                } else {
                    let options = list
                        .iter()
                        .take(80)
                        .map(|x| (x["number"].to_string(), s(x, "title")))
                        .collect();
                    self.overlays.push(Overlay::Pick {
                        title: "Which snapshot? (newest first)".into(),
                        options,
                        sel: 0,
                        then: Pick::Snapshot,
                    });
                }
            }
            Then::BootOptions => {
                let words: Vec<String> = v["words"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .filter_map(|w| w.as_str().map(String::from))
                    .collect();
                let presets: Vec<(String, String, String)> = v["presets"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .map(|p| (s(p, "word"), s(p, "label"), s(p, "hint")))
                    .collect();
                let on = presets.iter().map(|p| words.contains(&p.0)).collect();
                let other = words
                    .iter()
                    .filter(|w| !presets.iter().any(|p| &p.0 == *w))
                    .cloned()
                    .collect::<Vec<_>>()
                    .join(" ");
                self.overlays.push(Overlay::BootOptions {
                    words,
                    presets,
                    on,
                    sel: 0,
                    other,
                });
            }
            Then::EditCandidates => {
                let mut options: Vec<(String, String)> = v["files"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .filter_map(|f| f.as_str())
                    .map(|f| (f.to_string(), f.to_string()))
                    .collect();
                options.push(("__typed__".into(), "Another file… (type its path)".into()));
                self.overlays.push(Overlay::Pick {
                    title: "Which file? (it's backed up first)".into(),
                    options,
                    sel: 0,
                    then: Pick::EditFile,
                });
            }
            Then::EditOpen => {
                let path = s(&v, "open");
                let backup = s(&v, "backup");
                let editor = if which("micro") {
                    "micro"
                } else if which("nvim") {
                    "nvim"
                } else {
                    "nano"
                };
                self.message(
                    "Edited",
                    &if backup.is_empty() {
                        format!("{path}: a new file.")
                    } else {
                        format!("{path}: the version before is in {backup}.")
                    },
                    true,
                );
                return vec![Effect::Exec(vec![editor.into(), path])];
            }
            Then::Disks => {
                let text = v["disks"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .map(|d| {
                        format!(
                            "{}{}",
                            s(d, "verdict"),
                            if s(d, "model").is_empty() {
                                format!(" ({})", s(d, "size"))
                            } else {
                                format!(" ({}, {})", s(d, "model"), s(d, "size"))
                            }
                        )
                    })
                    .collect::<Vec<_>>()
                    .join("\n");
                let mounted = self.target().is_some();
                self.message(
                    "Check disks",
                    &if text.is_empty() {
                        "No drives found.".to_string()
                    } else {
                        text
                    },
                    true,
                );
                if mounted {
                    self.overlays.insert(self.overlays.len() - 1, Overlay::Progress { title: "btrfs's own check of the install (reads everything, changes nothing)".into(), lines: vec![], pct: None, done: None });
                    // the scrub runs after the drives' answers are read (the panel under this one)
                    return vec![Effect::Stream {
                        then: Then::Message("btrfs check".into()),
                        args: args(&["scrub"]),
                    }];
                }
            }
            Then::BackupTargets => {
                let options: Vec<(String, String)> = v["drives"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .map(|d| {
                        (
                            s(d, "path"),
                            format!("{} · {}", s(d, "describe"), s(d, "fstype")),
                        )
                    })
                    .collect();
                if options.is_empty() {
                    self.message("Back up my files to a USB drive", "Plug in a USB drive (formatted with ext4, exFAT, FAT or NTFS), then try again.", false);
                } else {
                    self.overlays.push(Overlay::Pick {
                        title: "Which drive?".into(),
                        options,
                        sel: 0,
                        then: Pick::BackupDrive,
                    });
                }
            }
            Then::Graphics => {
                let cards = v["cards"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .map(|c| {
                        let conn: Vec<String> = c["connected"]
                            .as_array()
                            .into_iter()
                            .flatten()
                            .filter_map(|x| x.as_str().map(String::from))
                            .collect();
                        format!(
                            "{}: {}",
                            s(c, "pci"),
                            if conn.is_empty() {
                                "no monitor".into()
                            } else {
                                format!("monitor on {}", conn.join(", "))
                            }
                        )
                    })
                    .collect::<Vec<_>>()
                    .join("\n");
                let lspci = s(&v, "lspci");
                self.message(
                    "Graphics: what's in this machine",
                    &format!(
                        "{}\n\n{}",
                        if cards.is_empty() {
                            "No graphics card with a display output found.".into()
                        } else {
                            cards
                        },
                        lspci
                    ),
                    true,
                );
            }
            Then::Remote => {
                let words = s(&v, "words");
                self.message(
                    "Remote help",
                    &if words.is_empty() {
                        "Remote help is off.".into()
                    } else {
                        words
                    },
                    true,
                );
                return vec![Effect::Call {
                    then: Then::Status,
                    args: args(&["status"]),
                    stdin: None,
                }];
            }
            Then::DiskPick(flow) => {
                let (title, options, then) = match flow {
                    Flow::Erase => (
                        "Which drive to erase?".to_string(),
                        disk_options(&v),
                        Pick::EraseDisk,
                    ),
                    Flow::ImageSource(action) => (
                        if action == "clone" {
                            "Copy which disk?".to_string()
                        } else {
                            "Image which disk or partition?".to_string()
                        },
                        disk_options(&v),
                        Pick::ImageSource(action),
                    ),
                    Flow::ImageTarget { action, from } => (
                        format!("Onto which disk? (from {from})"),
                        disk_options(&v)
                            .into_iter()
                            .filter(|(p, _)| *p != from)
                            .collect(),
                        Pick::ImageTarget { action, from },
                    ),
                };
                self.pick_or_say(&title, options, then);
            }
            Then::ImageList(action) => {
                let options: Vec<(String, String)> = v["images"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .map(|i| {
                        let mut words = vec![s(i, "name"), s(i, "size")];
                        let by = s(i, "made_by");
                        if !by.is_empty() {
                            words.push(format!("made by {by}"));
                        }
                        if !s(i, "disk").is_empty() {
                            words.push(format!("of {}", s(i, "disk")));
                        }
                        words.retain(|w| !w.is_empty());
                        (s(i, "path"), words.join(" · "))
                    })
                    .collect();
                let title = if action == "verify" {
                    "Check which image?"
                } else {
                    "Restore which image?"
                };
                self.pick_or_say(title, options, Pick::ImageChosen(action));
            }
            Then::ImageTargets(source) => {
                let mut options: Vec<(String, String)> = v["targets"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .map(|t| {
                        let mut words = vec![if s(t, "describe").is_empty() {
                            s(t, "path")
                        } else {
                            s(t, "describe")
                        }];
                        if !s(t, "kind").is_empty() {
                            words.push(s(t, "kind"));
                        }
                        (s(t, "path"), words.join(" · "))
                    })
                    .collect();
                options.push((
                    "__share__".into(),
                    "A share on your local network · smb:// or nfs://".into(),
                ));
                self.overlays.push(Overlay::Pick {
                    title: format!("Where should the image of {source} go?"),
                    options,
                    sel: 0,
                    then: Pick::ImageDest(source),
                });
            }
            Then::ShareMounted(source) => {
                let path = s(&v, "path");
                return self.image_create(source, path);
            }
            Then::ErasePlan(dev) => {
                let name = s(&v, "name");
                let name = if name.is_empty() {
                    dev_name(&dev)
                } else {
                    name
                };
                let mut about = vec![s(&v, "model"), s(&v, "size")];
                if !s(&v, "serial").is_empty() {
                    about.push(format!("serial {}", s(&v, "serial")));
                }
                about.retain(|w| !w.is_empty());
                let notes: Vec<String> = v["notes"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .filter_map(|n| n.as_str().map(String::from))
                    .collect();
                let rec = s(&v, "recommended");
                let methods: Vec<(String, String)> = v["methods"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .map(|m| {
                        let id = s(m, "id");
                        let what = s(m, "what");
                        let label = if id == rec {
                            format!("{what} · recommended")
                        } else {
                            what
                        };
                        (id, label)
                    })
                    .collect();
                let detail = format!(
                    "{dev}: {}{}",
                    about.join(" · "),
                    if notes.is_empty() {
                        String::new()
                    } else {
                        format!("\n\n{}", notes.join("\n"))
                    }
                );
                if methods.is_empty() {
                    self.message(
                        "Erase a disk securely",
                        &format!("{detail}\n\nField Kit has no way to erase this drive."),
                        false,
                    );
                } else {
                    let sel = methods.iter().position(|(id, _)| *id == rec).unwrap_or(0);
                    self.overlays.push(Overlay::Pick {
                        title: format!("How to erase {dev} ({})?", about.join(", ")),
                        options: methods,
                        sel,
                        then: Pick::EraseMethod { dev, name, detail },
                    });
                }
            }
            Then::WindowsFind => {
                let mut options: Vec<(String, String)> = Vec::new();
                for w in v["windows"].as_array().into_iter().flatten() {
                    let p = s(w, "path");
                    let what = if s(w, "label").is_empty() {
                        p.clone()
                    } else {
                        format!("{} ({p})", s(w, "label"))
                    };
                    if w["windows"].as_bool().unwrap_or(false) {
                        options.push((format!("pw:{p}"), format!("Reset a local account's password on {what} · the account gets an empty password")));
                    }
                    options.push((format!("fix:{p}"), format!("Fix common NTFS problems on {what} · Windows checks it at its next start")));
                }
                for b in v["bitlocker"].as_array().into_iter().flatten() {
                    let p = s(b, "path");
                    options.push((
                        format!("bl:{p}"),
                        format!(
                            "Open the BitLocker drive {p} ({}) · with its recovery key",
                            s(b, "size")
                        ),
                    ));
                }
                if v["uefi"].as_bool().unwrap_or(false) {
                    options.push(("boot:".into(), "Repair the boot entries · put Windows Boot Manager back, choose what starts first".into()));
                }
                self.pick_or_say(
                    "Windows repair: what should Field Kit do?",
                    options,
                    Pick::WindowsAction,
                );
            }
            Then::WindowsUsers(part) => {
                let warning = s(&v, "warning");
                let options: Vec<(String, String)> = v["users"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .map(|u| {
                        let mut tags = Vec::new();
                        if u["admin"].as_bool().unwrap_or(false) {
                            tags.push("administrator");
                        }
                        if u["locked"].as_bool().unwrap_or(false) {
                            tags.push("locked");
                        }
                        let n = s(u, "name");
                        (
                            n.clone(),
                            if tags.is_empty() {
                                n
                            } else {
                                format!("{n} · {}", tags.join(", "))
                            },
                        )
                    })
                    .collect();
                self.pick_or_say(
                    "Whose password? (a local account: it gets an empty password)",
                    options,
                    Pick::WindowsUser { part, warning },
                );
            }
            Then::BootEntries => {
                let entries: Vec<String> = v["entries"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .map(|e| {
                        format!(
                            "{} {}{}",
                            s(e, "num"),
                            s(e, "label"),
                            if e["active"].as_bool().unwrap_or(true) {
                                ""
                            } else {
                                " (off)"
                            }
                        )
                    })
                    .collect();
                let has_windows = v["entries"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .any(|e| e["windows"].as_bool().unwrap_or(false));
                let mut options = Vec::new();
                if !has_windows {
                    options.push((
                        "readd".to_string(),
                        "Put Windows Boot Manager back in the list".to_string(),
                    ));
                }
                options.push(("windows".into(), "Start Windows first".into()));
                options.push(("bromigos".into(), "Start bromigOS first".into()));
                let order = s(&v, "order");
                self.overlays.push(Overlay::Pick {
                    title: format!(
                        "The firmware's boot entries: {}{}",
                        if entries.is_empty() {
                            "none".into()
                        } else {
                            entries.join(", ")
                        },
                        if order.is_empty() {
                            String::new()
                        } else {
                            format!(" · order {order}")
                        }
                    ),
                    options,
                    sel: 0,
                    then: Pick::BootFix,
                });
            }
        }
        vec![]
    }

    /// The image of SOURCE into the folder DEST (a drive's, or a mounted share's).
    fn image_create(&mut self, source: String, dest: String) -> Vec<Effect> {
        self.overlays.push(Overlay::Progress {
            title: "Make an image".into(),
            lines: vec![],
            pct: None,
            done: None,
        });
        vec![Effect::Stream {
            then: Then::Message("Make an image".into()),
            args: vec![
                "image".into(),
                "create".into(),
                "--source".into(),
                source,
                "--dest".into(),
                dest,
            ],
        }]
    }

    /// A choice, or a plain word when there's nothing to choose from.
    fn pick_or_say(&mut self, title: &str, options: Vec<(String, String)>, then: Pick) {
        if options.is_empty() {
            self.message(
                title,
                "Nothing to choose from here: connect the drive (or the share) and try again.",
                false,
            );
        } else {
            self.overlays.push(Overlay::Pick {
                title: title.into(),
                options,
                sel: 0,
                then,
            });
        }
    }

    /// The server's facts arrived.
    pub fn server_facts(&mut self, v: Value) {
        self.server = v;
    }

    /// The overview's temperatures, added to their recent readings (the last 24, about six
    /// minutes at one every 15 seconds); a sensor that's gone drops out.
    fn keep_temps(&mut self, v: &Value) {
        let now: Vec<(String, f64)> = v["computer"]["temps"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|t| Some((s(t, "label"), t["celsius"].as_f64()?)))
            .collect();
        let mut kept = Vec::new();
        for (label, c) in now {
            let mut hist = self
                .temps
                .iter()
                .find(|(l, _)| *l == label)
                .map(|(_, h)| h.clone())
                .unwrap_or_default();
            hist.push(c);
            let skip = hist.len().saturating_sub(24);
            kept.push((label, hist.split_off(skip)));
        }
        self.temps = kept;
    }

    /// Something on screen moves on its own: Home's orb, the Lab's scan (never under reduced
    /// motion, never under a dialog). The run loop redraws about every 120 ms for it.
    pub fn animating(&self) -> bool {
        self.look.motion
            && self.overlays.is_empty()
            && (self.screen == Screen::Home
                || (self.screen == Screen::Section
                    && SECTIONS[self.section] == "Lab"
                    && self.lab["cards"].as_array().is_some_and(|c| !c.is_empty())))
    }

    pub fn moving(&self) -> bool {
        self.look.motion
            && (self.spark_until.is_some_and(|t| Instant::now() < t)
                || matches!(
                    self.overlays.last(),
                    Some(Overlay::Busy { .. }) | Some(Overlay::Progress { done: None, .. })
                ))
    }
}

/// A device's own name (/dev/sdb -> sdb), what a typed confirmation asks for.
fn dev_name(dev: &str) -> String {
    Path::new(dev)
        .file_name()
        .map(|n| n.to_string_lossy().to_string())
        .unwrap_or_else(|| dev.to_string())
}

fn disk_options(v: &Value) -> Vec<(String, String)> {
    v["disks"]
        .as_array()
        .into_iter()
        .flatten()
        .map(|d| {
            let mut words = vec![s(d, "path"), s(d, "size")];
            if !s(d, "model").is_empty() {
                words.push(s(d, "model"));
            }
            (s(d, "path"), words.join(" · "))
        })
        .collect()
}

fn findings(v: &Value) -> Vec<Finding> {
    v["findings"]
        .as_array()
        .into_iter()
        .flatten()
        .map(|f| Finding {
            id: s(f, "id"),
            title: s(f, "title"),
            detail: s(f, "detail"),
            fix: s(f, "fix"),
            ok: f["ok"].as_bool().unwrap_or(false),
            result: String::new(),
            fixed_at: None,
            commands: strings(&f["commands"]),
            touches: strings(&f["touches"]),
        })
        .collect()
}

fn strings(v: &Value) -> Vec<String> {
    v.as_array()
        .into_iter()
        .flatten()
        .filter_map(|x| x.as_str().map(String::from))
        .collect()
}

/// Bytes as base64 (OSC 52's clipboard payload).
pub fn base64(data: &[u8]) -> String {
    const T: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::new();
    for c in data.chunks(3) {
        let n = (u32::from(c[0]) << 16)
            | (u32::from(*c.get(1).unwrap_or(&0)) << 8)
            | u32::from(*c.get(2).unwrap_or(&0));
        out.push(T[(n >> 18) as usize & 63] as char);
        out.push(T[(n >> 12) as usize & 63] as char);
        out.push(if c.len() > 1 {
            T[(n >> 6) as usize & 63] as char
        } else {
            '='
        });
        out.push(if c.len() > 2 {
            T[n as usize & 63] as char
        } else {
            '='
        });
    }
    out
}

/// A shell argument, quoted when it needs to be.
fn shq(a: &str) -> String {
    if !a.is_empty()
        && a.chars()
            .all(|c| c.is_ascii_alphanumeric() || "-_./=:,+@%".contains(c))
    {
        a.to_string()
    } else {
        format!("'{}'", a.replace('\'', "'\\''"))
    }
}

/// A confirm dialog's buttons: go ahead, "Show the commands" when the action has them, Cancel.
pub fn confirm_labels(yes: &str, then: &Pick) -> Vec<String> {
    let mut v = vec![yes.to_string()];
    if pick_plan(then).is_some() {
        v.push("Show the commands".into());
    }
    v.push("Cancel".into());
    v
}

/// A confirmed choice's commands.
fn pick_plan(then: &Pick) -> Option<PlanSrc> {
    Some(match then {
        Pick::RollbackYes(n) => PlanSrc::Engine {
            args: vec!["plan".into(), "rollback".into(), n.clone()],
            cli: format!("bromigos fieldkit repair rollback {n} --dry-run"),
        },
        Pick::GrubYes => PlanSrc::Engine {
            args: args(&["plan", "grub-repair"]),
            cli: "bromigos fieldkit repair boot-menu --dry-run".into(),
        },
        Pick::Power(p) => local(
            &[&format!("systemctl {p}")],
            &["the whole machine"],
            &format!("systemctl {p}"),
            "",
        ),
        Pick::RemoteToggle(on) => {
            let w = if *on { "on" } else { "off" };
            local(
                &[&format!("fieldkit-engine remote {w}")],
                &[
                    "sshd.service",
                    "/etc/ssh/sshd_config.d/20-bromigos-remote.conf",
                ],
                &format!("bromigos fieldkit remote {w}"),
                "",
            )
        }
        Pick::WindowsResetYes { part, user } => local(
            &[&format!(
                "fieldkit-engine engine windows reset-password --part {part} --user {}",
                shq(user)
            )],
            &[&format!(
                "{part}: Windows' account database (SAM), backed up first"
            )],
            &format!(
                "bromigos fieldkit windows reset-password --part {part} --user {}",
                shq(user)
            ),
            "",
        ),
        _ => return None,
    })
}

/// What an action touches, in a line (the hint and its confirm dialog say it; the engine's
/// plan gives the exact paths).
pub fn act_touches(a: &Act) -> String {
    match a {
        Act::Mount => "unlocks the disk you choose; mounts it at /mnt/bromigos".into(),
        Act::Unmount => "/mnt/bromigos and the disk's lock".into(),
        Act::Why => "reads the install's journal; changes nothing".into(),
        Act::Black => "reads only; each fix names the files it changes, backed up first".into(),
        Act::Rollback => {
            "the install's root (@ is kept as @.before-rollback-…) and /boot's kernel".into()
        }
        Act::Grub => "GRUB on the disk, /boot/grub/grub.cfg, the firmware's boot entry".into(),
        Act::BootOptions => "/etc/default/grub and /boot/grub/grub.cfg".into(),
        Act::Edit => "the file you choose, backed up first".into(),
        Act::Disks => "reads every drive; changes nothing".into(),
        Act::Backup => "adds a folder on the USB drive you choose".into(),
        Act::Image => "the disks you choose (an image is only read from its source)".into(),
        Act::Erase => "everything on the disk you choose".into(),
        Act::Windows => "the Windows partition you choose".into(),
        Act::Graphics => "reads only".into(),
        Act::Remote => "sshd.service and /etc/ssh/sshd_config.d/20-bromigos-remote.conf".into(),
        Act::MakeStick => "everything on the USB drive you choose".into(),
        Act::InstallEdition(_) => "the disk you choose in the installer".into(),
        Act::ServerUpdate => "packages, after a snapshot (rolled back if unhealthy)".into(),
        Act::Firewall(_, set) => format!("the nftables rule set {set}"),
        Act::ServerSsh => "sshd.service".into(),
        Act::Power(_) => "the whole machine (the install is unmounted first)".into(),
        _ => String::new(),
    }
}

/// Where an action's commands come from: the engine's plan (exact), or known here.
#[derive(Debug, Clone, PartialEq)]
pub enum PlanSrc {
    Engine {
        args: Vec<String>,
        cli: String,
    },
    Local {
        commands: Vec<String>,
        touches: Vec<String>,
        cli: String,
        note: String,
    },
}

fn local(commands: &[&str], touches: &[&str], cli: &str, note: &str) -> PlanSrc {
    PlanSrc::Local {
        commands: commands.iter().map(|c| c.to_string()).collect(),
        touches: touches.iter().map(|c| c.to_string()).collect(),
        cli: cli.into(),
        note: note.into(),
    }
}

fn which(cmd: &str) -> bool {
    std::env::var_os("PATH")
        .map(|p| std::env::split_paths(&p).any(|d| d.join(cmd).is_file()))
        .unwrap_or(false)
}

fn installer() -> String {
    std::env::var("BROMIGOS_FIELDKIT_INSTALLER")
        .unwrap_or_else(|_| "/usr/local/bin/bromigos-iso-install".into())
}

// ------------------------------------------------------------------ drawing (view.rs)

mod view;
#[cfg(test)]
pub use view::facts;
pub use view::{bar_chips, chip_spans, chips_width, draw, home_layout, item_at};

// ------------------------------------------------------------------ the run loop

enum Ev {
    Key(KeyEvent),
    Lab(Value),
    Click(u16, u16),
    Hover(u16, u16),
    Resize,
    Reply(Then, Value),
    Progress(Option<u8>, String),
    Server(Value),
}

/// One JSON document from the engine (its last line).
pub fn engine_call(a: &[String], stdin: Option<&str>) -> Value {
    engine_call_with(&engine_path(), a, stdin)
}

/// The same, with this engine (tests give their own, never through the environment).
pub fn engine_call_with(engine: &str, a: &[String], stdin: Option<&str>) -> Value {
    let mut cmd = Command::new(engine);
    cmd.arg("engine")
        .args(a)
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    cmd.stdin(if stdin.is_some() {
        Stdio::piped()
    } else {
        Stdio::null()
    });
    let Ok(mut child) = cmd.spawn() else {
        return json!({"ok": false, "message": "Field Kit's engine isn't installed (bromigos-fieldkit-tools)."});
    };
    if let (Some(text), Some(mut w)) = (stdin, child.stdin.take()) {
        let _ = w.write_all(text.as_bytes());
    }
    let out = child.wait_with_output();
    match out {
        Ok(o) => {
            let text = String::from_utf8_lossy(&o.stdout);
            let last = text
                .lines()
                .rev()
                .find(|l| l.trim_start().starts_with('{'))
                .unwrap_or("");
            if o.status.code() == Some(2) {
                return json!({"ok": false, "message": "That isn't on this Field Kit yet."});
            }
            serde_json::from_str(last).unwrap_or_else(
                |_| json!({"ok": false, "message": "Field Kit's engine gave no answer."}),
            )
        }
        Err(e) => json!({"ok": false, "message": format!("Field Kit's engine failed: {e}")}),
    }
}

fn engine_stream(a: &[String], tx: &mpsc::Sender<Ev>, then: Then) {
    engine_stream_with(&engine_path(), a, tx, then)
}

fn engine_stream_with(engine: &str, a: &[String], tx: &mpsc::Sender<Ev>, then: Then) {
    let mut cmd = Command::new(engine);
    cmd.arg("engine")
        .args(a)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .stdin(Stdio::null());
    let Ok(mut child) = cmd.spawn() else {
        let _ = tx.send(Ev::Reply(
            then,
            json!({"ok": false, "message": "Field Kit's engine isn't installed."}),
        ));
        return;
    };
    let mut last = Value::Null;
    if let Some(out) = child.stdout.take() {
        for line in BufReader::new(out)
            .lines()
            .map_while(std::result::Result::ok)
        {
            let v: Value = serde_json::from_str(&line).unwrap_or_else(|_| json!({"line": line}));
            if v.get("progress").is_some() || (v.get("line").is_some() && v.get("ok").is_none()) {
                let pct = v["progress"].as_u64().map(|p| p.min(100) as u8);
                let _ = tx.send(Ev::Progress(pct, s(&v, "line")));
            } else {
                last = v;
            }
        }
    }
    let code = child.wait().ok().and_then(|c| c.code());
    if last.is_null() {
        last = if code == Some(2) {
            json!({"ok": false, "message": "That isn't on this Field Kit yet."})
        } else {
            json!({"ok": false, "message": "The job ended without saying how."})
        };
    }
    let _ = tx.send(Ev::Reply(then, last));
}

/// The lab's cards (`bromigos lab status --json`): its machines and services, for the Lab
/// screen. Nothing when there's no lab console or no lab configured.
pub fn lab_status() -> Value {
    Command::new("bromigos")
        .args(["lab", "status", "--json"])
        .stdin(Stdio::null())
        .stderr(Stdio::null())
        .output()
        .ok()
        .and_then(|o| serde_json::from_slice::<Value>(&o.stdout).ok())
        .unwrap_or(Value::Null)
}

/// This machine's facts for the server home screen.
pub fn server_facts() -> Value {
    let server =
        Path::new("/usr/share/bromigos/server").is_dir() || Path::new(SERVER_STATUS).is_file();
    let hostname = std::fs::read_to_string("/etc/hostname")
        .map(|h| h.trim().to_string())
        .unwrap_or_default();
    let addrs: Vec<String> = Command::new("ip")
        .args(["-4", "-o", "addr", "show", "scope", "global"])
        .output()
        .map(|o| {
            String::from_utf8_lossy(&o.stdout)
                .lines()
                .filter_map(|l| {
                    l.split_whitespace()
                        .nth(3)
                        .map(|a| a.split('/').next().unwrap_or("").to_string())
                })
                .collect()
        })
        .unwrap_or_default();
    let ssh = Command::new("systemctl")
        .args(["is-active", "--quiet", "sshd.service"])
        .status()
        .is_ok_and(|s| s.success());
    let status = if Path::new(SERVER_STATUS).is_file() {
        Command::new(SERVER_STATUS)
            .args(["status", "--json"])
            .output()
            .ok()
            .and_then(|o| serde_json::from_slice::<Value>(&o.stdout).ok())
            .unwrap_or(Value::Null)
    } else {
        Value::Null
    };
    json!({"server": server, "hostname": hostname, "addresses": addrs, "ssh": ssh, "status": status})
}

/// The menu, until someone leaves it: "shell", "reboot", "poweroff" or nothing.
pub fn run_menu() -> Result<Option<String>> {
    let mut app = App::new(Look::detect());
    let (tx, rx) = mpsc::channel::<Ev>();
    let do_effects = |effects: Vec<Effect>, tx: &mpsc::Sender<Ev>| -> Vec<Effect> {
        let mut rest = Vec::new();
        for e in effects {
            match e {
                Effect::Call { then, args, stdin } => {
                    let tx = tx.clone();
                    std::thread::spawn(move || {
                        let v = engine_call(&args, stdin.as_deref());
                        let _ = tx.send(Ev::Reply(then, v));
                    });
                }
                Effect::Stream { then, args } => {
                    let tx = tx.clone();
                    std::thread::spawn(move || engine_stream(&args, &tx, then));
                }
                Effect::Server => {
                    let tx = tx.clone();
                    std::thread::spawn(move || {
                        let _ = tx.send(Ev::Server(server_facts()));
                    });
                }
                Effect::Lab => {
                    let tx = tx.clone();
                    std::thread::spawn(move || {
                        let _ = tx.send(Ev::Lab(lab_status()));
                    });
                }
                other => rest.push(other),
            }
        }
        rest
    };
    {
        let tx = tx.clone();
        std::thread::spawn(move || {
            while let Ok(e) = event::read() {
                let ev = match e {
                    Event::Key(k) => Ev::Key(k),
                    Event::Mouse(m) if m.kind == MouseEventKind::Down(MouseButton::Left) => {
                        Ev::Click(m.column, m.row)
                    }
                    Event::Mouse(m) if m.kind == MouseEventKind::Moved => {
                        Ev::Hover(m.column, m.row)
                    }
                    // the wheel moves the selection (the list scrolls to keep it in view)
                    Event::Mouse(m)
                        if matches!(
                            m.kind,
                            MouseEventKind::ScrollDown | MouseEventKind::ScrollUp
                        ) =>
                    {
                        let code = if m.kind == MouseEventKind::ScrollDown {
                            KeyCode::Down
                        } else {
                            KeyCode::Up
                        };
                        Ev::Key(KeyEvent::new(code, KeyModifiers::NONE))
                    }
                    // a resize: the next frame lays everything out again at the new size
                    Event::Resize(_, _) => Ev::Resize,
                    _ => continue,
                };
                if tx.send(ev).is_err() {
                    return;
                }
            }
        });
    }
    let mut terminal = ratatui::init();
    let _ = execute!(std::io::stdout(), EnableMouseCapture);
    let mut pending = do_effects(app.start(), &tx);
    let mut last_status = Instant::now();
    let result = loop {
        for e in std::mem::take(&mut pending) {
            match e {
                Effect::Quit(r) => {
                    let _ = execute!(std::io::stdout(), DisableMouseCapture);
                    ratatui::restore();
                    return Ok(r);
                }
                Effect::Vector | Effect::Pair => {
                    let _ = execute!(std::io::stdout(), DisableMouseCapture);
                    ratatui::restore();
                    let engine = std::path::PathBuf::from(engine_path());
                    let r = if e == Effect::Pair {
                        crate::fieldkit_vector::pair::pair(&app.look, &engine)
                    } else {
                        crate::fieldkit_vector::run(&app.look, &engine)
                    };
                    if let Err(e) = r {
                        eprintln!("VECTOR: {e}");
                        std::thread::sleep(Duration::from_secs(2));
                    }
                    terminal = ratatui::init();
                    let _ = execute!(std::io::stdout(), EnableMouseCapture);
                    let _ = terminal.clear();
                }
                Effect::Copy(text) => {
                    // OSC 52: the terminal puts it on its clipboard (if it takes OSC 52)
                    print!("\x1b]52;c;{}\x07", base64(text.as_bytes()));
                    let _ = std::io::stdout().flush();
                }
                Effect::Exec(argv) => {
                    let _ = execute!(std::io::stdout(), DisableMouseCapture);
                    ratatui::restore();
                    print!("\x1b[2J\x1b[H");
                    let _ = std::io::stdout().flush();
                    let r = Command::new(&argv[0]).args(&argv[1..]).status();
                    if let Err(e) = r {
                        eprintln!("{}: {e}", argv[0]);
                        std::thread::sleep(Duration::from_secs(2));
                    }
                    terminal = ratatui::init();
                    let _ = execute!(std::io::stdout(), EnableMouseCapture);
                    let _ = terminal.clear();
                    pending.extend(do_effects(
                        vec![Effect::Call {
                            then: Then::Status,
                            args: args(&["status"]),
                            stdin: None,
                        }],
                        &tx,
                    ));
                }
                _ => {}
            }
        }
        if let Ok(sz) = terminal.size() {
            app.size = Rect::new(0, 0, sz.width, sz.height);
        }
        if let Err(e) = terminal.draw(|f| draw(f, &app)) {
            break Err(e.into());
        }
        let wait = if app.moving() {
            Duration::from_millis(80)
        } else if app.animating() {
            Duration::from_millis(120)
        } else {
            Duration::from_millis(1000)
        };
        match rx.recv_timeout(wait) {
            Ok(Ev::Key(k)) => pending = do_effects(app.key(k), &tx),
            Ok(Ev::Click(x, y)) => pending = do_effects(app.click(x, y), &tx),
            Ok(Ev::Hover(x, y)) => app.hover(x, y),
            Ok(Ev::Resize) => {}
            Ok(Ev::Reply(then, v)) => pending = do_effects(app.reply(then, v), &tx),
            Ok(Ev::Progress(p, l)) => app.progress(p, l),
            Ok(Ev::Server(v)) => app.server_facts(v),
            Ok(Ev::Lab(v)) => app.lab = v,
            Err(mpsc::RecvTimeoutError::Timeout) => {}
            Err(mpsc::RecvTimeoutError::Disconnected) => break Ok(None),
        }
        app.tick = app.tick.wrapping_add(1);
        if app.spark_until.is_some_and(|t| Instant::now() >= t) {
            app.spark_until = None;
        }
        if last_status.elapsed() > Duration::from_secs(15) && app.overlays.is_empty() {
            last_status = Instant::now();
            pending.extend(do_effects(
                vec![
                    Effect::Call {
                        then: Then::Status,
                        args: args(&["status"]),
                        stdin: None,
                    },
                    Effect::Call {
                        then: Then::Overview,
                        args: args(&["overview"]),
                        stdin: None,
                    },
                    Effect::Server,
                ],
                &tx,
            ));
        }
    };
    let _ = execute!(std::io::stdout(), DisableMouseCapture);
    ratatui::restore();
    result
}

fn ensure_root(words: &[OsString]) {
    // SAFETY: geteuid has no preconditions.
    if unsafe { libc::geteuid() } == 0 || std::env::var_os("BROMIGOS_FIELDKIT_NO_ROOT").is_some() {
        return;
    }
    let exe = std::env::current_exe().unwrap_or_else(|_| "bromigos".into());
    let err = Command::new("sudo")
        .arg("--preserve-env=BROMIGOS_FIELDKIT_ENGINE,BROMIGOS_FIELDKIT_SETTINGS,COLORTERM,TERM,BROMIGOS_REDUCED_MOTION")
        .arg(exe)
        .arg("fieldkit")
        .args(words)
        .exec();
    eprintln!("bromigos fieldkit: this needs root, and sudo didn't start: {err}");
    std::process::exit(1);
}

fn after_menu(r: Option<String>) -> Result<i32> {
    match r.as_deref() {
        Some(p @ ("reboot" | "poweroff")) => {
            let _ = engine_call(&args(&["unmount"]), None);
            let err = Command::new("systemctl").arg(p).exec();
            Err(err.into())
        }
        _ => Ok(0),
    }
}

// ------------------------------------------------------------------ the shapes, for Python

/// A console colour's name, as rich and Textual spell it (the 16 colours bromigos-boot sets).
fn ansi_name(c: ratatui::style::Color) -> &'static str {
    use ratatui::style::Color::*;
    match c {
        Black => "black",
        Red => "red",
        Green => "green",
        Yellow => "yellow",
        Blue => "blue",
        Magenta => "magenta",
        Cyan => "cyan",
        Gray => "white",
        DarkGray => "bright_black",
        LightRed => "bright_red",
        LightGreen => "bright_green",
        LightYellow => "bright_yellow",
        LightBlue => "bright_blue",
        LightMagenta => "bright_magenta",
        LightCyan => "bright_cyan",
        White => "bright_white",
        _ => "default",
    }
}

/// An orb's frames as rows of characters and rows of its glow (`*` where a cell glows).
fn orb_frames(rows_at: impl Fn(f64) -> Vec<Vec<(char, bool)>>, frames: usize) -> Vec<Value> {
    (0..frames)
        .map(|i| {
            let rows = rows_at(i as f64 * 0.12);
            let text: Vec<String> = rows
                .iter()
                .map(|r| r.iter().map(|c| c.0).collect())
                .collect();
            let hot: Vec<String> = rows
                .iter()
                .map(|r| r.iter().map(|c| if c.1 { '*' } else { ' ' }).collect())
                .collect();
            json!({"rows": text, "hot": hot})
        })
        .collect()
}

/// DRIFTGLASS's shapes from their source here, for the Python TUIs (the installer's;
/// lib/bromigos_drift.py): the palette in use and what the terminal shows, the emblem and the
/// wordmarks, `frames` frames of the orb `orb` cells big (one each 0.12 s, as Home draws them)
/// and the plain ring's, and the disk map's rules.
pub fn shapes(look: &Look, orb: (usize, usize), frames: usize) -> Value {
    use bromigos_tui::orb as o;
    let ansi = bromigos_tui::Pal::ansi16();
    let roles = ansi.roles_json();
    let ansi16: serde_json::Map<String, Value> = roles
        .as_object()
        .into_iter()
        .flatten()
        .map(|(k, _)| (k.clone(), Value::from(ansi_name(ansi.role(k)))))
        .collect();
    let mode = match look.mode {
        bromigos_tui::Mode::Truecolor => "truecolor",
        bromigos_tui::Mode::Ansi16 => "ansi16",
        bromigos_tui::Mode::Mono => "mono",
    };
    json!({
        "palette": {
            "mode": mode, "ascii": look.ascii, "motion": look.motion, "nerd": look.nerd,
            "braille": o::fine(look),
            "colors": bromigos_tui::palette::load().0.roles_json(),
            "ansi16": ansi16,
        },
        "emblem": bromigos_tui::emblem::emblem_rows(),
        "wordmark": bromigos_tui::emblem::WORDMARK,
        "wordmark_ascii": bromigos_tui::emblem::WORDMARK_ASCII,
        "orb": {
            "size": [orb.0, orb.1],
            "seconds_per_frame": 0.12,
            "frames": orb_frames(|t| o::braille(t, orb.0, orb.1), frames),
            "glow": "a glowing cell is white and bold, the rest the primary colour",
            "plain": {
                "size": [o::PLAIN.0, o::PLAIN.1],
                "frames": orb_frames(o::plain, frames),
            },
        },
        "disk_map": bromigos_tui::diskmap::rules(),
    })
}

/// `bromigos fieldkit shapes [--json] [--orb WxH] [--frames N]`: (the orb's size, frames).
fn shapes_args(words: &[String]) -> std::result::Result<((usize, usize), usize), String> {
    let (mut orb, mut frames) = ((22, 11), 12);
    let mut it = words.iter();
    while let Some(w) = it.next() {
        match w.as_str() {
            "--json" => {}
            "--orb" => {
                let v = it.next().ok_or("--orb needs a size, such as 22x11")?;
                let (a, b) = v.split_once('x').ok_or("--orb takes WxH, such as 22x11")?;
                orb = (
                    a.parse().map_err(|_| format!("not a width: {a}"))?,
                    b.parse().map_err(|_| format!("not a height: {b}"))?,
                );
                if !(2..=200).contains(&orb.0) || !(1..=100).contains(&orb.1) {
                    return Err("the orb is 2 to 200 cells wide and 1 to 100 high".into());
                }
            }
            "--frames" => {
                let v = it.next().ok_or("--frames needs a number")?;
                frames = v.parse().map_err(|_| format!("not a number: {v}"))?;
                frames = frames.clamp(1, 600);
            }
            other => return Err(format!("unknown: {other}")),
        }
    }
    Ok((orb, frames))
}

/// `bromigos fieldkit [WORDS…]`.
pub fn fieldkit_cmd(words: Vec<OsString>) -> Result<i32> {
    let first = words.first().and_then(|w| w.to_str()).unwrap_or("");
    match first {
        "" | "menu" => {
            ensure_root(&words);
            let r = run_menu()?;
            after_menu(r)
        }
        "vector" => {
            crate::fieldkit_vector::run(&Look::detect(), Path::new(&engine_path()))?;
            Ok(0)
        }
        "console" => {
            ensure_root(&words);
            let shell = if which("zsh") { "zsh" } else { "bash" };
            loop {
                let r = run_menu()?;
                if matches!(r.as_deref(), Some("reboot" | "poweroff")) {
                    return after_menu(r);
                }
                println!("\nField Kit's menu is closed. Type exit to come back to it.\n");
                let _ = Command::new(shell).arg("-l").status();
            }
        }
        "shapes" => {
            let rest: Vec<String> = words[1..]
                .iter()
                .map(|w| w.to_string_lossy().into_owned())
                .collect();
            match shapes_args(&rest) {
                Ok((orb, frames)) => {
                    println!("{}", shapes(&Look::detect(), orb, frames));
                    Ok(0)
                }
                Err(e) => {
                    eprintln!("bromigos fieldkit shapes: {e}");
                    Ok(2)
                }
            }
        }
        "-h" | "--help" | "help" => {
            println!(
                "bromigos fieldkit: Field Kit, bromigOS without the desktop (docs/fieldkit.md)\n\n  \
                 bromigos fieldkit             the menu: Repair, Lab, Tools, Install, Shell\n  \
                 bromigos fieldkit repair black-screen|last-boot|rollback N|boot-menu|boot-options [--set …]\n  \
                 bromigos fieldkit mount DEV | unmount | disks | scrub | backup DEV | overview\n  \
                                               (each with --json, --dry-run, --yes)\n  \
                 bromigos fieldkit why         what went wrong on the last boot, in plain words\n  \
                 bromigos fieldkit black-screen [--fix]   the causes of a black screen at startup\n  \
                 bromigos fieldkit status      whether Field Kit is in this machine's boot menu\n  \
                 bromigos fieldkit make-stick [DEVICE]    a Field Kit USB stick with your settings\n  \
                 bromigos fieldkit remote on|off|status   remote help over SSH\n  \
                 bromigos fieldkit usb [DEVICE]           write Field Kit onto a USB drive\n  \
                 bromigos fieldkit shapes --json [--orb WxH] [--frames N]\n  \
                                               DRIFTGLASS's shapes for the Python TUIs"
            );
            Ok(0)
        }
        _ => {
            let err = Command::new(engine_path()).args(&words).exec();
            eprintln!(
                "bromigos fieldkit: Field Kit's engine didn't start ({err}): install bromigos-fieldkit-tools"
            );
            Ok(1)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use ratatui::Terminal;
    use ratatui::backend::TestBackend;
    use ratatui::crossterm::event::KeyEventState;

    /// A fake engine: canned answers by verb, so the screens run without root or disks.
    const FAKE: &str = r#"#!/bin/sh
[ "$1" = engine ] || exit 2
shift
case "$1 $2" in
  "plan grub-repair") echo '{"ok":true,"action":"grub-repair","commands":["arch-chroot /mnt/bromigos grub-install --target=x86_64-efi --efi-directory=/boot --removable","arch-chroot /mnt/bromigos grub-mkconfig -o /boot/grub/grub.cfg.fieldkit-new"],"touches":["/boot/EFI/BOOT/BOOTX64.EFI","/boot/grub/grub.cfg"]}' ;;
  "overview "*) echo '{"ok":true,"version":"2026.10.30","network":{"kind":"wired","state":"lan","name":"enp1s0"},"ssh":{"on":false},"stick":"stick settings: 1 SSH key(s)","remote":{"on":false},"computer":{"board":"QEMU Standard PC (Q35 + ICH9, 2009)","cpu":"AMD Ryzen 9 7950X 16-Core Processor (4 threads)","ram":"4.0 GB","gpus":["Red Hat Virtio 1.0 GPU (virtio_gpu)"],"temps":[{"label":"CPU","celsius":41.0},{"label":"GPU","celsius":55.0}]},"load":{"cpu_pct":31.0,"mem_pct":62.5},"disks":[{"name":"vda","path":"/dev/vda","size":256060514304,"model":"","tran":"","health":"ok","parts":[{"name":"vda1","path":"/dev/vda1","size":1073741824,"fstype":"vfat","label":"","parttypename":"EFI System"},{"name":"vda2","path":"/dev/vda2","size":137438953472,"fstype":"crypto_LUKS","label":"","parttypename":"Linux filesystem"},{"name":"vda3","path":"/dev/vda3","size":16777216,"fstype":"","label":"","parttypename":"Microsoft reserved"},{"name":"vda4","path":"/dev/vda4","size":85899345920,"fstype":"BitLocker","label":"","parttypename":"Microsoft basic data"}]}],"found":[{"kind":"bromigos","title":"bromigOS","device":"vda2","state":"encrypted, locked","detail":"","health":"ok"},{"kind":"windows","title":"Windows 11","device":"vda4","state":"BitLocker on","detail":"","health":"ok"},{"kind":"fieldkit","title":"Field Kit stick","device":"sr0","state":"","detail":"this medium"}],"suggestions":[]}' ;;
  "status "*) echo '{"ok":true,"live":true,"network":"none","remote":{"on":false},"remote_words":"","stick":"stick settings: 1 SSH key(s)","target":{"root":"/mnt/bromigos","hostname":"echo","mounted_by_fieldkit":true,"users":["tester"]}}' ;;
  "check black-screen") echo '{"ok":true,"findings":[{"id":"0","title":"The login screen starts: sddm.service","detail":"","fix":"","ok":true},{"id":"1","title":"A login screen setting left in /etc/sddm.conf.d/10-gpu.conf.disabled","detail":"It is named 10-gpu.conf.disabled, which looks switched off, but SDDM reads every file in that folder.","fix":"Move it out (kept in a backup)","ok":false,"commands":["mkdir -p /mnt/bromigos/var/lib/bromigos/fieldkit-backups/x/etc/sddm.conf.d","mv /mnt/bromigos/etc/sddm.conf.d/10-gpu.conf.disabled /mnt/bromigos/var/lib/bromigos/fieldkit-backups/x/etc/sddm.conf.d/"],"touches":["/etc/sddm.conf.d/10-gpu.conf.disabled"]},{"id":"2","title":"The startup files module list is wrong (/etc/mkinitcpio.conf)","detail":"nvidia-open is a package, not a module (the module is nvidia).","fix":"Correct it and rebuild the startup files","ok":false}]}' ;;
  "fix black-screen") echo "{\"ok\":true,\"message\":\"Fixed finding $3. The old file is in /var/lib/bromigos/fieldkit-backups/x.\"}" ;;
  "disks "*) echo '{"ok":true,"disks":[{"path":"/dev/sda","model":"Field Disk","size":"64.0 GB","verdict":"/dev/sda: the drive says it is healthy.","failing":false},{"path":"/dev/sdb","model":"USB Stick","size":"16.0 GB","verdict":"/dev/sdb: ok","failing":false}]}' ;;
  "erase plan") echo '{"ok":true,"device":"/dev/sdb","name":"sdb","model":"USB Stick","serial":"FK123","transport":"usb","rotational":false,"bytes":16000000000,"size":"16.0 GB","methods":[{"id":"blkdiscard","what":"Discard every block (fast; flash drives)"},{"id":"overwrite","what":"Overwrite it once with zeros, then check"}],"recommended":"overwrite","notes":["This USB stick has no secure erase of its own."]}' ;;
  "erase run") echo '{"progress":10,"line":"overwriting"}'; echo '{"progress":100,"line":"checking"}'; echo "{\"ok\":true,\"report\":\"/run/archiso/bootmnt/fieldkit/erase-sdb.txt\",\"message\":\"Erased $3 with $7. Report saved.\"}" ;;
  "image list") echo '{"ok":true,"images":[{"path":"/run/usb/2026-10-30-sda-img","name":"2026-10-30-sda-img","disk":"sda","parts":["sda1","sda2"],"filesystems":{"sda1":"vfat","sda2":"btrfs"},"bytes":1,"size":"12.1 GB","made_by":"Clonezilla","whole_disk":true}]}' ;;
  "image targets") echo '{"ok":true,"targets":[{"path":"/run/usb","describe":"/dev/sdc1 · 64 GB · Backup","fstype":"exfat","kind":"USB drive","mounted":true}]}' ;;
  "image mount-share") echo '{"ok":true,"message":"Connected.","path":"/run/bromigos-fieldkit/share"}' ;;
  "image restore"|"image create") echo '{"progress":50,"line":"partclone"}'; echo "{\"ok\":true,\"message\":\"$1 $2 $3 $4 $5 $6 $7 $8 $9\"}" ;;
  "windows find") echo '{"ok":true,"windows":[{"path":"/dev/sda3","size":"200 GB","label":"Windows","windows":true,"note":""}],"bitlocker":[],"boot_manager":true,"entries":[],"order":"","uefi":true}' ;;
  "windows users") echo '{"ok":true,"users":[{"rid":500,"name":"Administrator","admin":true,"locked":true},{"rid":1001,"name":"Sam","admin":true,"locked":false}],"warning":"Files Sam encrypted with Windows (EFS) can no longer be opened after this."}' ;;
  "windows reset-password") echo "{\"ok\":true,\"message\":\"Sam has no password now.\",\"warning\":\"\",\"backup\":\"/x\"}" ;;
  *) exit 2 ;;
esac
"#;

    /// The fake engine's path (passed to drive(), never set in the environment: other
    /// modules' tests run in the same process).
    fn fake() -> String {
        static ONCE: std::sync::Once = std::sync::Once::new();
        let dir =
            std::env::temp_dir().join(format!("bromigos-fieldkit-fake-{}", std::process::id()));
        let p = dir.join("fieldkit-engine");
        ONCE.call_once(|| {
            std::fs::create_dir_all(&dir).unwrap();
            std::fs::write(&p, FAKE).unwrap();
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&p, std::fs::Permissions::from_mode(0o755)).unwrap();
        });
        p.to_string_lossy().to_string()
    }

    fn key(c: KeyCode) -> KeyEvent {
        KeyEvent {
            code: c,
            modifiers: KeyModifiers::NONE,
            kind: KeyEventKind::Press,
            state: KeyEventState::NONE,
        }
    }

    /// Does the effects the way the run loop does, but here and now.
    fn drive(app: &mut App, mut effects: Vec<Effect>) -> Vec<Effect> {
        let mut rest = Vec::new();
        while let Some(e) = effects.pop() {
            match e {
                Effect::Call { then, args, stdin } => {
                    let v = engine_call_with(&fake(), &args, stdin.as_deref());
                    effects.extend(app.reply(then, v));
                }
                Effect::Stream { then, args } => {
                    let (tx, rx) = mpsc::channel();
                    engine_stream_with(&fake(), &args, &tx, then);
                    drop(tx);
                    for ev in rx {
                        match ev {
                            Ev::Progress(p, l) => app.progress(p, l),
                            Ev::Reply(t, v) => effects.extend(app.reply(t, v)),
                            _ => {}
                        }
                    }
                }
                Effect::Server => {}
                other => rest.push(other),
            }
        }
        rest
    }

    /// A folder of stand-in commands: the Tools cards see these, not the build machine's PATH.
    fn tool_dir() -> std::path::PathBuf {
        let dir =
            std::env::temp_dir().join(format!("bromigos-fieldkit-tools-{}", std::process::id()));
        if !dir.is_dir() {
            std::fs::create_dir_all(&dir).unwrap();
            for c in [
                "btop", "htop", "nvtop", "gdu", "fzf", "rg", "mtr", "iperf3", "nvim", "micro",
                "lazygit", "tmux", "herdr", "photorec", "cfdisk", "bromigos", "less", "inxi",
                "sensors", "watch",
            ] {
                std::fs::write(dir.join(c), "").unwrap();
            }
        }
        dir
    }

    fn app() -> App {
        fake();
        let mut look = Look::wick();
        look.motion = false;
        let mut a = App::new(look);
        a.path = Some(vec![tool_dir()]);
        let start = a.start();
        drive(&mut a, start);
        a
    }

    fn screen(app: &App, w: u16, h: u16) -> String {
        let mut t = Terminal::new(TestBackend::new(w, h)).unwrap();
        t.draw(|f| draw(f, app)).unwrap();
        let b = t.backend().buffer();
        let mut s = String::new();
        for y in 0..b.area.height {
            for x in 0..b.area.width {
                s.push_str(b[(x, y)].symbol());
            }
            while s.ends_with(' ') {
                s.pop();
            }
            s.push('\n');
        }
        s
    }

    /// The screens as text, for looking at: into $BROMIGOS_FIELDKIT_SHOTS when it's set.
    fn save(name: &str, text: &str) {
        if let Some(dir) = std::env::var_os("BROMIGOS_FIELDKIT_SHOTS") {
            let _ = std::fs::write(Path::new(&dir).join(format!("tui-{name}.txt")), text);
        }
    }

    #[test]
    fn menu_shows_sections_and_status() {
        let mut a = app();
        assert!(a.live());
        a.open_section(0);
        let s = screen(&a, 160, 40);
        save("menu", &s);
        assert!(s.contains("BROMIGOS // FIELD KIT"), "{s}");
        assert!(s.contains("Fix a black screen / blinking cursor at startup"));
        assert!(s.contains("wired · local only"), "{s}");
        assert!(s.contains("Home › Repair"), "{s}");
        assert!(s.contains("mounted at /mnt/bromigos"), "{s}");
        // mounted already: Mount is gone, Unmount is there
        assert!(!s.contains("Mount my bromigOS install"));
    }

    #[test]
    fn install_offers_the_desktop_only_online() {
        let mut a = app();
        let fx = a.open_section(5);
        drive(&mut a, fx);
        let labels: Vec<_> = a.items().iter().map(|i| i.label).collect();
        assert!(labels.contains(&"bromigOS Server (no desktop)"));
        // the desktop's card is there, saying it needs the internet; choosing it says why
        let desk = a
            .items()
            .into_iter()
            .find(|i| i.label == "bromigOS desktop")
            .unwrap();
        assert_eq!(
            a.badge(&desk),
            Some(("needs the internet".into(), Tone::Warn))
        );
        let s = screen(&a, 100, 30);
        save("install", &s);
        assert!(
            s.contains("needs the internet")
                && s.contains("BEFORE INSTALLING")
                && s.contains("BitLocker is on"),
            "{s}"
        );
        assert!(a.choose(&desk).is_empty());
        assert!(
            matches!(a.overlays.last(), Some(Overlay::Message { text, .. }) if text.contains("internet"))
        );
        a.overlays.clear();
        a.overview["network"]["state"] = json!("internet");
        assert_eq!(a.badge(&desk), None);
    }

    #[test]
    fn lab_says_it_needs_the_local_network() {
        let mut a = app();
        a.overview["network"]["state"] = json!("none");
        a.section = 1;
        let lab = a.items()[0].clone();
        assert_eq!(a.blocked(&lab), "needs your local network");
        let fx = a.choose(&lab);
        assert!(fx.is_empty());
        assert!(
            matches!(a.overlays.last(), Some(Overlay::Message { text, .. }) if text.contains("local network"))
        );
    }

    #[test]
    fn black_screen_findings_and_a_fix() {
        let mut a = app();
        a.open_section(0);
        let i = a.items().iter().position(|i| i.act == Act::Black).unwrap();
        a.sel = i;
        let fx = a.key(key(KeyCode::Enter));
        drive(&mut a, fx);
        let Some(Overlay::Findings { items, sel, .. }) = a.overlays.last() else {
            panic!("{:?}", a.overlays)
        };
        assert_eq!(items.len(), 3);
        assert_eq!(*sel, 1, "the first fixable finding is chosen");
        save("black-screen", &screen(&a, 110, 34));
        let fx = a.key(key(KeyCode::Enter));
        drive(&mut a, fx);
        let Some(Overlay::Findings { items, sel, .. }) = a.overlays.last() else {
            panic!()
        };
        assert!(
            items[1].result.starts_with("Fixed finding 1"),
            "{:?}",
            items[1]
        );
        assert_eq!(*sel, 2, "on to the next fix");
        assert!(items[1].fixed_at.is_some());
        save("black-screen-fixed", &screen(&a, 110, 34));
    }

    /// The findings' marks: ✓ fine or fixed, ▲ a problem with a fix, ✕ one without, each in its
    /// colour; a fix that just worked flashes its ✓ and the panel's edge (never under reduced
    /// motion).
    #[test]
    fn findings_show_their_severity_and_a_fix_sparks() {
        let mut a = app();
        a.open_section(0);
        a.sel = a.items().iter().position(|i| i.act == Act::Black).unwrap();
        let fx = a.key(key(KeyCode::Enter));
        drive(&mut a, fx);
        if let Some(Overlay::Findings { items, .. }) = a.overlays.last_mut() {
            items[2].fix.clear();
        }
        let cell = |a: &App, mark: &str| {
            let mut t = Terminal::new(TestBackend::new(110, 34)).unwrap();
            t.draw(|f| draw(f, a)).unwrap();
            let b = t.backend().buffer().clone();
            (0..34)
                .flat_map(|y| (0..110).map(move |x| (x, y)))
                .find(|&(x, y)| b[(x, y)].symbol() == mark && x < 4)
                .map(|(x, y)| b[(x, y)].clone())
        };
        let p = a.look.pal;
        assert_eq!(cell(&a, "✓").unwrap().fg, p.primary);
        assert_eq!(cell(&a, "▲").unwrap().fg, p.warn);
        assert_eq!(cell(&a, "✕").unwrap().fg, p.danger);
        save("finding-severity", &screen(&a, 110, 34));
        // the fix: its ✓ flashes white for a second while motion is allowed
        a.look.motion = true;
        let fx = a.key(key(KeyCode::Enter));
        drive(&mut a, fx);
        let mut t = Terminal::new(TestBackend::new(110, 34)).unwrap();
        t.draw(|f| draw(f, &a)).unwrap();
        let b = t.backend().buffer();
        let flashed = (0..34).any(|y| b[(2, y)].symbol() == "✓" && b[(2, y)].fg == p.white);
        assert!(flashed, "the fixed one's ✓ flashes");
        assert!(
            (0..110).any(|x| b[(x, 2)].fg == p.soft),
            "the panel's edge sparks"
        );
        // and in ASCII, plain marks
        a.look.ascii = true;
        let s = screen(&a, 110, 34);
        assert!(s.contains("ok ") && s.contains("x  "), "{s}");
    }

    #[test]
    fn erase_needs_the_disk_typed() {
        let mut a = app();
        a.open_section(0);
        let i = a.items().iter().position(|i| i.act == Act::Erase).unwrap();
        a.sel = i;
        let fx = a.key(key(KeyCode::Enter));
        drive(&mut a, fx);
        // pick /dev/sdb
        a.key(key(KeyCode::Down));
        let fx = a.key(key(KeyCode::Enter));
        drive(&mut a, fx);
        // the methods, the recommended one chosen
        let Some(Overlay::Pick {
            title,
            sel,
            options,
            ..
        }) = a.overlays.last()
        else {
            panic!("{:?}", a.overlays)
        };
        assert!(
            title.contains("USB Stick") && title.contains("serial FK123"),
            "{title}"
        );
        assert_eq!(options[*sel].0, "overwrite");
        save("erase-method", &screen(&a, 110, 34));
        a.key(key(KeyCode::Enter));
        assert!(
            matches!(a.overlays.last(), Some(Overlay::Typed { want, detail, .. }) if want == "sdb" && detail.contains("no secure erase"))
        );
        for c in "sda".chars() {
            a.key(key(KeyCode::Char(c)));
        }
        assert!(
            a.key(key(KeyCode::Enter)).is_empty(),
            "the wrong name does nothing"
        );
        save("erase-confirm", &screen(&a, 110, 34));
        a.key(key(KeyCode::Backspace));
        a.key(key(KeyCode::Char('b')));
        let fx = a.key(key(KeyCode::Enter));
        assert!(
            matches!(&fx[..], [Effect::Stream { args, .. }] if args.join(" ") == "erase run /dev/sdb --confirm sdb --method overwrite"),
            "{fx:?}"
        );
        drive(&mut a, fx);
        let Some(Overlay::Progress {
            done: Some((ok, msg)),
            lines,
            ..
        }) = a.overlays.last()
        else {
            panic!("{:?}", a.overlays)
        };
        assert!(
            *ok && msg.contains("Erased /dev/sdb with overwrite"),
            "{msg}"
        );
        assert_eq!(lines.len(), 2);
        save("erase-done", &screen(&a, 110, 34));
    }

    #[test]
    fn a_missing_engine_verb_says_so_plainly() {
        let mut a = app();
        a.open_section(0);
        let i = a
            .items()
            .iter()
            .position(|i| i.act == Act::Windows)
            .unwrap();
        a.sel = i;
        let fx = a.key(key(KeyCode::Enter));
        drive(&mut a, fx);
        let Some(Overlay::Pick { options, .. }) = a.overlays.last() else {
            panic!("{:?}", a.overlays)
        };
        assert_eq!(options[0].0, "pw:/dev/sda3");
        assert!(options.iter().any(|o| o.0 == "boot:"));
        // a password: the account, then the warning, plainly, before anything changes
        let fx = a.key(key(KeyCode::Enter));
        drive(&mut a, fx);
        a.key(key(KeyCode::Down));
        a.key(key(KeyCode::Enter));
        let Some(Overlay::Confirm { detail, sel, .. }) = a.overlays.last() else {
            panic!("{:?}", a.overlays)
        };
        assert!(detail.contains("EFS"), "{detail}");
        assert_eq!(*sel, 1, "Cancel is the default");
        save("windows-reset", &screen(&a, 110, 34));
        a.key(key(KeyCode::Left));
        let fx = a.key(key(KeyCode::Enter));
        assert!(
            matches!(&fx[..], [Effect::Call { args, .. }] if args.join(" ") == "windows reset-password --part /dev/sda3 --user Sam"),
            "{fx:?}"
        );
        drive(&mut a, fx);
        assert!(
            matches!(a.overlays.last(), Some(Overlay::Message { ok: true, text, .. }) if text.contains("no password"))
        );
        a.overlays.clear();
        let fx = a.call("x", Then::Message("Copy".into()), &["image", "nonsense"]);
        drive(&mut a, fx);
        assert!(
            matches!(a.overlays.last(), Some(Overlay::Message { text, .. }) if text.contains("isn't on this Field Kit yet"))
        );
    }

    #[test]
    fn restore_asks_for_the_target_by_name_and_a_share_works() {
        let mut a = app();
        let fx = a.picked(Pick::ImageAction, "restore".into());
        drive(&mut a, fx);
        let Some(Overlay::Pick { options, .. }) = a.overlays.last() else {
            panic!("{:?}", a.overlays)
        };
        assert!(options[0].1.contains("made by Clonezilla"), "{options:?}");
        let fx = a.key(key(KeyCode::Enter));
        drive(&mut a, fx);
        // onto /dev/sdb (the fake's second disk)
        a.key(key(KeyCode::Down));
        a.key(key(KeyCode::Enter));
        for c in "sdb".chars() {
            a.key(key(KeyCode::Char(c)));
        }
        let fx = a.key(key(KeyCode::Enter));
        assert!(
            matches!(&fx[..], [Effect::Stream { args, .. }]
            if args.join(" ") == "image restore --image /run/usb/2026-10-30-sda-img --target /dev/sdb --confirm sdb"),
            "{fx:?}"
        );
        a.overlays.clear();
        // an image onto a share on the local network
        let fx = a.picked(Pick::ImageSource("create".into()), "/dev/sda".into());
        drive(&mut a, fx);
        let Some(Overlay::Pick { options, .. }) = a.overlays.last() else {
            panic!()
        };
        assert_eq!(options.last().unwrap().0, "__share__");
        a.key(key(KeyCode::Up));
        a.key(key(KeyCode::Enter));
        for c in "nfs://nas/images".chars() {
            a.key(key(KeyCode::Char(c)));
        }
        let fx = a.key(key(KeyCode::Enter));
        assert!(
            matches!(&fx[..], [Effect::Call { args, .. }] if args.join(" ") == "image mount-share nfs://nas/images"),
            "{fx:?}"
        );
        let fx = drive(&mut a, fx);
        assert!(fx.is_empty());
        let Some(Overlay::Progress {
            done: Some((ok, msg)),
            ..
        }) = a.overlays.last()
        else {
            panic!("{:?}", a.overlays)
        };
        assert!(
            *ok && msg.contains("--dest /run/bromigos-fieldkit/share"),
            "{msg}"
        );
    }

    /// The overlay owns its rows: nothing of the menu's panels shows to its left or right, and
    /// a wrapped description goes on under its own first word, not at the panel's edge.
    #[test]
    fn overlays_cover_the_menu_and_wrap_with_a_hanging_indent() {
        let mut a = app();
        a.open_section(0);
        let i = a.items().iter().position(|i| i.act == Act::Black).unwrap();
        a.sel = i;
        let fx = a.key(key(KeyCode::Enter));
        drive(&mut a, fx);
        let (w, h) = (64u16, 34u16);
        let s = screen(&a, w, h);
        let head = widgets::emitter_height(&a.look, h) as usize;
        let rows: Vec<&str> = s.lines().collect();
        let body = &rows[head..rows.len() - 2];
        let border = |c: char| "│╭╰╮╯┃".contains(c);
        for r in body {
            let chars: Vec<char> = r.chars().collect();
            assert!(
                border(chars[0]),
                "the overlay's frame starts the row: {r:?}"
            );
            let inside: String = chars[1..chars.len().saturating_sub(1)].iter().collect();
            assert!(
                !inside.contains(['│', '╭', '╮', '╰', '╯']),
                "another panel shows through: {r:?}"
            );
            assert!(!r.contains("SECTIONS") && !r.contains("1 Repair"), "{r:?}");
        }
        // the long detail wraps, every line of it starting in the same column
        let at = body
            .iter()
            .position(|r| r.contains("which looks"))
            .expect(&s);
        let col = |r: &str| r.chars().skip(1).position(|c| c != ' ').unwrap();
        let start = col(body[at]);
        let mut n = 0;
        for r in &body[at..] {
            if r.contains('[') || r.chars().skip(1).all(|c| c == ' ' || c == '│') {
                break;
            }
            assert_eq!(col(r), start, "a continuation line out of step: {r:?}\n{s}");
            n += 1;
        }
        assert!(n >= 2, "the detail wraps at this width:\n{s}");
        // and the finding's title sits after its marker, its wrapped rest under the title
        let t = body
            .iter()
            .position(|r| r.contains("▲ A login screen"))
            .expect(&s);
        assert_eq!(col(body[t + 1]), col(body[t]) + 2, "{s}");
        save("black-screen-narrow", &s);
    }

    #[test]
    fn console_and_ascii_looks() {
        let mut a = app();
        a.look = Look::from_parts(
            bromigos_tui::Pal::wick(),
            "full",
            &|k: &str| (k == "TERM").then(|| "linux".to_string()),
            "",
        );
        let s = screen(&a, 100, 30);
        save("menu-console", &s);
        assert!(s.contains("FIELD KIT"));
        a.look.ascii = true;
        let s = screen(&a, 100, 30);
        save("menu-ascii", &s);
        assert!(s.lines().all(|l| l.is_ascii()), "{s}");
    }

    fn console_look() -> Look {
        Look::from_parts(
            bromigos_tui::Pal::wick(),
            "full",
            &|k: &str| (k == "TERM").then(|| "linux".to_string()),
            "",
        )
    }

    #[test]
    fn home_at_two_sizes() {
        let mut a = app();
        assert_eq!(a.screen, Screen::Home);
        for (w, h) in [(100u16, 30u16), (160, 48)] {
            let s = screen(&a, w, h);
            save(&format!("home-{w}x{h}"), &s);
            for want in [
                "THIS COMPUTER",
                "FOUND ON THIS COMPUTER",
                "BROMIGOS // FIELD KIT",
                "2026.10.30",
                "SSH off",
                "wired",
                "AMD Ryzen",
                "bromigOS on vda2",
                "BitLocker on",
            ] {
                assert!(s.contains(want), "{want} at {w}x{h}:\n{s}");
            }
            for name in SECTIONS {
                assert!(s.contains(name), "{name} at {w}x{h}:\n{s}");
            }
            assert!(!s.contains("Suggested"), "no suggestions, no box:\n{s}");
            // the tiles don't overlap and fill the grid
            let l = home_layout(&a, Rect::new(0, 0, w, h));
            for (i, r) in l.tiles.iter().enumerate() {
                assert!(r.width >= 10 && r.height >= 3, "{i}: {r:?}");
                for q in &l.tiles[i + 1..] {
                    assert!(r.intersection(*q).is_empty(), "{r:?} {q:?}");
                }
            }
        }
        // the big screen in 24-bit colour shows the emblem: braille
        assert!(screen(&a, 160, 48).contains('⣿'));
        a.look = console_look();
        let s = screen(&a, 100, 30);
        save("home-console", &s);
        assert!(
            !s.contains('\u{f0ad}'),
            "the console's font has no Nerd glyphs: fallbacks"
        );
        a.look.ascii = true;
        a.look.nerd = false;
        let s = screen(&a, 100, 30);
        save("home-ascii", &s);
        assert!(s.lines().all(|l| l.is_ascii()), "{s}");
        let s = screen(&a, 150, 45);
        save("home-ascii-150x45", &s);
        assert!(s.lines().all(|l| l.is_ascii()), "{s}");
        assert!(s.contains("(@)"), "the plain ring:\n{s}");
    }

    /// Home's live parts: the meters, the temperatures' recent readings, the disk map, the
    /// drives' verdicts, and the orb, which moves only while motion is allowed.
    #[test]
    fn home_shows_readings_disks_and_the_orb() {
        let mut a = app();
        // four refreshes: the temperatures have a history
        for c in [44.0, 52.0, 61.0, 93.0] {
            let mut v = a.overview.clone();
            v["computer"]["temps"][0]["celsius"] = json!(c);
            a.reply(Then::Overview, v);
        }
        assert_eq!(a.temps[0].1, vec![41.0, 44.0, 52.0, 61.0, 93.0]);
        let s = screen(&a, 150, 45);
        save("home-150-live", &s);
        for want in [
            "busy",
            "31%",
            "memory",
            "62%",
            "CPU 93°C",
            "▂▃▄▄▇",
            " bromigOS ",
            " Windows ",
            "● healthy",
        ] {
            assert!(s.contains(want), "{want}:\n{s}");
        }
        // a failing drive says so, in the found list and on its disk
        a.overview["found"][0]["health"] = json!("failing");
        assert!(screen(&a, 150, 45).contains("FAILING"));
        // the orb: still under reduced motion, moving with it; Home asks for redraws only then
        assert!(!a.animating());
        let still = screen(&a, 150, 45);
        a.tick = 40;
        assert_eq!(still, screen(&a, 150, 45), "reduced motion holds it still");
        a.look.motion = true;
        assert!(a.animating());
        assert_ne!(still, screen(&a, 150, 45), "the scan goes round");
        a.overlays.push(Overlay::Busy { title: "x".into() });
        assert!(!a.animating(), "not under a dialog");
        // the console's look: the plain ring, no braille
        a.overlays.clear();
        a.look = console_look();
        let s = screen(&a, 150, 45);
        save("home-console-150-live", &s);
        assert!(s.contains("(@)") || s.contains("(o)"), "{s}");
        assert!(
            !s.chars().any(|c| ('\u{2801}'..='\u{28ff}').contains(&c)),
            "{s}"
        );
    }

    #[test]
    fn tiles_move_open_and_go_back() {
        let mut a = app();
        a.key(key(KeyCode::Right));
        assert_eq!(a.home, HomeSel::Tile(1));
        a.key(key(KeyCode::Down));
        assert_eq!(a.home, HomeSel::Tile(4), "three a row at 100 columns");
        let fx = a.key(key(KeyCode::Enter));
        drive(&mut a, fx);
        assert_eq!((a.screen, SECTIONS[a.section]), (Screen::Section, "Server"));
        let s = screen(&a, 100, 30);
        assert!(s.contains("Home › Server"), "{s}");
        a.key(key(KeyCode::Esc));
        assert_eq!((a.screen, a.home), (Screen::Home, HomeSel::Tile(4)));
        // VECTOR's tile hands the screen to its own module
        assert_eq!(a.key(key(KeyCode::Char('3'))), vec![Effect::Vector]);
        assert_eq!(a.screen, Screen::Home);
        a.key(key(KeyCode::Char('4')));
        assert_eq!((a.screen, SECTIONS[a.section]), (Screen::Section, "Tools"));
        // Tools is a grid of cards: right moves along, down a row (two a row at 100 columns)
        a.key(key(KeyCode::Right));
        a.key(key(KeyCode::Down));
        assert_eq!(a.sel, 3);
        save("tools", &screen(&a, 100, 30));
        a.key(key(KeyCode::Esc));
        // a click on a tile opens it
        a.size = Rect::new(0, 0, 100, 30);
        let r = home_layout(&a, a.size).tiles[4];
        a.click(r.x + 2, r.y + 1);
        assert_eq!(SECTIONS[a.section], "Server");
        let s = screen(&a, 100, 30);
        save("section-server", &s);
        assert!(
            s.contains("Install bromigOS Server") && s.contains("What bromigOS Server is"),
            "{s}"
        );
        a.key(key(KeyCode::Esc));
        a.key(key(KeyCode::Char('1')));
        save("section-repair", &screen(&a, 100, 30));
        a.look = console_look();
        save("section-repair-console", &screen(&a, 100, 30));
    }

    #[test]
    fn home_uses_its_rows_from_the_top() {
        let mut a = app();
        // wide: each tile has its line about it; the lab and the recent repairs when known
        a.overview["lab"] =
            json!({"name": "LAB", "sources": 3, "kinds": ["kubernetes", "prometheus"]});
        a.overview["recent"] =
            json!([{"when": "2026-10-30 14:02", "what": "black screen", "backup": "/x"}]);
        let s = screen(&a, 150, 45);
        save("home-150-lab", &s);
        assert!(
            s.contains("fix what's broken") || s.contains("fix an install"),
            "{s}"
        );
        assert!(s.contains("Lab: LAB · 3 services"), "{s}");
        assert!(s.contains("Recent: black screen 2026-10-30 14:02"), "{s}");
        // tiny: the list starts under the top bar, and no line about a section is cut mid-word
        let a = app();
        let s = screen(&a, 60, 17);
        save("home-60x17", &s);
        let rows: Vec<&str> = s.lines().collect();
        assert!(
            rows[2].contains("Repair")
                || rows[3].contains("Repair")
                || rows[2].contains("THIS COMPUTER"),
            "{s}"
        );
        assert!(!s.lines().skip(2).take(13).any(|r| r.contains('…')), "{s}");
    }

    #[test]
    fn suggestions_only_when_there_are_some() {
        let mut a = app();
        a.key(key(KeyCode::Up));
        assert_eq!(a.home, HomeSel::Tile(0), "no suggestion to go up to");
        a.home = HomeSel::Tile(0);
        a.overview["suggestions"] = json!([{"text": "bromigOS on vda2 didn't finish starting last time → Find out why", "action": "why", "device": "vda2"}]);
        let s = screen(&a, 100, 30);
        save("home-suggested", &s);
        assert!(
            s.contains("Suggested") && s.contains("didn't finish starting"),
            "{s}"
        );
        a.key(key(KeyCode::Up));
        assert_eq!(a.home, HomeSel::Suggestion(0));
        let fx = a.key(key(KeyCode::Enter));
        assert!(
            fx.iter().any(
                |e| matches!(e, Effect::Call { args, .. } if args.join(" ") == "check last-boot")
            ),
            "{fx:?}"
        );
        assert_eq!(SECTIONS[a.section], "Repair");
    }

    #[test]
    fn both_looks_of_the_repair_screens() {
        for (look, name) in [(Look::wick(), "nerd"), (console_look(), "console")] {
            let mut a = app();
            a.look = look;
            a.look.motion = false;
            a.open_section(0);
            let i = a.items().iter().position(|i| i.act == Act::Black).unwrap();
            a.sel = i;
            let fx = a.key(key(KeyCode::Enter));
            drive(&mut a, fx);
            save(&format!("black-screen-{name}"), &screen(&a, 100, 30));
            a.overlays.clear();
            let fx = a.picked(Pick::EraseDisk, "/dev/sdb".into());
            drive(&mut a, fx);
            a.key(key(KeyCode::Enter));
            save(&format!("erase-confirm-{name}"), &screen(&a, 100, 30));
        }
    }

    #[test]
    fn server_actions_use_bromigos_server_and_systemctl() {
        let mut a = app();
        a.status["live"] = json!(false);
        a.server = json!({"server": true, "hostname": "node1", "ssh": true, "status": {"firewall": "on (SSH, lab-cluster)", "updates": "automatic, nightly"}});
        a.open_section(4);
        let s = screen(&a, 150, 40);
        save("section-server-installed", &s);
        assert!(
            s.contains("THIS SERVER") && s.contains("firewall: on (SSH, lab-cluster)"),
            "{s}"
        );
        // narrower: the gist on one line above the actions
        let s = screen(&a, 100, 30);
        assert!(
            s.contains("node1 · SSH on") && !s.contains("THIS SERVER"),
            "{s}"
        );
        assert!(!s.contains("Install bromigOS Server"), "{s}");
        let run = |a: &mut App, label: &str| {
            let it = a.items().into_iter().find(|i| i.label == label).unwrap();
            match &a.choose(&it)[..] {
                [Effect::Exec(argv)] => argv.join(" "),
                other => format!("{other:?}"),
            }
        };
        a.overview["network"]["state"] = json!("internet");
        assert_eq!(
            run(&mut a, "Update now"),
            format!("{SERVER_STATUS} update --now")
        );
        assert_eq!(
            run(&mut a, "Let the web in"),
            format!("{SERVER_STATUS} firewall allow web")
        );
        assert_eq!(
            run(&mut a, "Close it to the lab's cluster"),
            format!("{SERVER_STATUS} firewall deny lab-cluster")
        );
        assert_eq!(
            run(&mut a, "SSH on or off"),
            "systemctl disable --now sshd.service"
        );
    }

    /// A lab's status, as `bromigos lab status --json` gives it: four parts, one not answering.
    fn lab_cards() -> Value {
        json!({"configured": true, "state": "warn", "cards": [
            {"id": "nodes", "title": "node-a", "state": "ok", "summary": "gpu, 2x RTX 3090"},
            {"id": "k3s", "title": "k3s", "state": "ok", "summary": "3 nodes"},
            {"id": "nas", "title": "nas", "state": "ok", "summary": "storage, 71% full"},
            {"id": "node-c", "title": "node-c", "state": "unreachable", "summary": "not answering for 2 h"}]})
    }

    /// `bromigos fieldkit shapes`: the palette, the emblem, the orb's frames and the disk
    /// map's rules, as the Python TUIs read them.
    #[test]
    fn shapes_for_the_python_tuis() {
        let args = |w: &[&str]| shapes_args(&w.iter().map(|s| s.to_string()).collect::<Vec<_>>());
        assert_eq!(args(&["--json"]), Ok(((22, 11), 12)));
        assert_eq!(args(&["--orb", "10x5", "--frames", "3"]), Ok(((10, 5), 3)));
        assert!(args(&["--orb", "ten"]).is_err() && args(&["--what"]).is_err());
        let v = shapes(&Look::wick(), (10, 5), 3);
        assert_eq!(v["palette"]["mode"], "truecolor");
        assert_eq!(v["palette"]["ansi16"]["primary"], "green");
        assert!(
            v["palette"]["colors"]["primary"]
                .as_str()
                .unwrap()
                .starts_with('#')
        );
        assert!(v["emblem"].as_array().unwrap().len() >= 8);
        let frames = v["orb"]["frames"].as_array().unwrap();
        assert_eq!(frames.len(), 3);
        assert_eq!(frames[0]["rows"].as_array().unwrap().len(), 5);
        assert_eq!(
            frames[0]["rows"][0].as_str().unwrap().chars().count(),
            frames[0]["hot"][0].as_str().unwrap().chars().count()
        );
        assert_ne!(frames[0], frames[2], "the scan goes round");
        assert_eq!(
            v["orb"]["plain"]["frames"][0]["rows"]
                .as_array()
                .unwrap()
                .len(),
            5
        );
        let kinds = v["disk_map"]["kinds"].as_array().unwrap();
        assert!(kinds.iter().any(|k| k["kind"] == "bromigos"));
    }

    /// The Lab on a wide screen: its parts round the lab as a map, with their names and the
    /// list under it; narrower, or on the console, the list alone. The map's scan moves only
    /// with motion allowed.
    #[test]
    fn the_lab_as_a_map_on_wide_screens() {
        let mut a = app();
        let fx = a.open_section(1);
        drive(&mut a, fx);
        a.lab = lab_cards();
        let s = screen(&a, 150, 45);
        save("lab-150-map", &s);
        assert!(s.contains("THE LAB'S MAP") && s.contains('◉'), "{s}");
        for name in ["node-a", "k3s", "nas", "node-c"] {
            assert_eq!(
                s.matches(name).count(),
                2,
                "{name} on the map and in the list:\n{s}"
            );
        }
        assert!(s.contains("not answering for 2 h"), "{s}");
        let s = screen(&a, 120, 35);
        assert!(!s.contains("THE LAB'S MAP") && s.contains("node-c"), "{s}");
        assert!(!a.animating(), "reduced motion");
        a.look.motion = true;
        assert!(a.animating(), "the scan goes round");
        a.look = console_look();
        let s = screen(&a, 150, 45);
        assert!(!s.contains("THE LAB'S MAP") && s.contains("node-c"), "{s}");
    }

    /// Every screen, in both looks, for the operator: shots/tui-<screen>-<look>.txt.
    #[test]
    fn every_screen_in_both_looks() {
        for (name, look) in [("nerd", Look::wick()), ("console", console_look())] {
            let mut a = app();
            a.look = look;
            a.look.motion = false;
            let (w, h) = (110, 34);
            save(&format!("home-{name}"), &screen(&a, w, h));
            for (i, sec) in SECTIONS.iter().enumerate() {
                if *sec == "VECTOR" {
                    continue;
                }
                let fx = a.open_section(i);
                drive(&mut a, fx);
                if *sec == "Lab" {
                    a.lab = lab_cards();
                }
                let s = screen(&a, w, h);
                assert!(
                    s.contains(&format!("Home › {sec}"))
                        || s.contains(&format!("Home > {sec}"))
                        || s.contains(sec),
                    "{s}"
                );
                save(&format!("{}-{name}", sec.to_lowercase()), &s);
            }
            // a finding, over Repair
            let fx = a.open_section(0);
            drive(&mut a, fx);
            let i = a.items().iter().position(|i| i.act == Act::Black).unwrap();
            a.sel = i;
            let fx = a.key(key(KeyCode::Enter));
            drive(&mut a, fx);
            let s = screen(&a, w, h);
            save(&format!("finding-{name}"), &s);
            assert!(s.contains("Fix a black screen"), "{s}");
            a.overlays.clear();
            // the Repair screen's badge now counts what it found
            let s = screen(&a, w, h);
            assert!(s.contains("2 found"), "{s}");
            save(&format!("repair-after-check-{name}"), &s);
        }
    }

    #[test]
    fn letters_jump_from_anywhere_but_not_into_a_text_field() {
        let mut a = app();
        // from Home
        a.key(key(KeyCode::Char('t')));
        assert_eq!((a.screen, SECTIONS[a.section]), (Screen::Section, "Tools"));
        // from a section, to another
        a.key(key(KeyCode::Char('s')));
        assert_eq!(SECTIONS[a.section], "Server");
        assert_eq!(a.key(key(KeyCode::Char('v'))), vec![Effect::Vector]);
        let fx = a.key(key(KeyCode::Char('R')));
        drive(&mut a, fx);
        assert_eq!(SECTIONS[a.section], "Repair");
        // over a list of choices a letter still jumps (the list goes)
        a.overlays.push(Overlay::Pick {
            title: "x".into(),
            options: vec![("a".into(), "a".into())],
            sel: 0,
            then: Pick::Snapshot,
        });
        a.key(key(KeyCode::Char('l')));
        assert!(a.overlays.is_empty());
        assert_eq!(SECTIONS[a.section], "Lab");
        // while typing, letters are text; Alt+letter jumps
        a.overlays.push(Overlay::Input {
            title: "Unlock".into(),
            prompt: "".into(),
            value: String::new(),
            hidden: true,
            then: Pick::Passphrase("/dev/vda2".into()),
        });
        for c in "trivial".chars() {
            a.key(key(KeyCode::Char(c)));
        }
        assert!(
            matches!(a.overlays.last(), Some(Overlay::Input { value, .. }) if value == "trivial")
        );
        assert_eq!(SECTIONS[a.section], "Lab");
        let alt = KeyEvent {
            code: KeyCode::Char('x'),
            modifiers: KeyModifiers::ALT,
            kind: KeyEventKind::Press,
            state: KeyEventState::NONE,
        };
        // Alt+X: a shell, from inside the field; the field is still there after it
        let fx = a.key(alt);
        assert!(
            matches!(&fx[..], [Effect::Exec(argv)] if argv.last().map(String::as_str) == Some("-l")),
            "{fx:?}"
        );
        assert!(
            matches!(a.overlays.last(), Some(Overlay::Input { value, .. }) if value == "trivial")
        );
        assert_eq!(SECTIONS[a.section], "Lab");
        a.overlays.clear();
        a.key(key(KeyCode::Char('7')));
        a.screen = Screen::Home;
        let fx = a.key(key(KeyCode::Char('7')));
        drive(&mut a, fx);
        assert_eq!(SECTIONS[a.section], "Shell", "the Shell section is tile 7");
        // a running job keeps the screen
        a.overlays.push(Overlay::Progress {
            title: "Erasing".into(),
            lines: vec![],
            pct: None,
            done: None,
        });
        a.key(key(KeyCode::Char('r')));
        assert!(!a.overlays.is_empty());
        assert_eq!(SECTIONS[a.section], "Shell");
    }

    #[test]
    fn question_mark_opens_the_keys_page_and_f_the_suggestion() {
        let mut a = app();
        a.key(key(KeyCode::Char('?')));
        let Some(Overlay::Keys { title, rows, .. }) = a.overlays.last() else {
            panic!("{:?}", a.overlays)
        };
        assert_eq!(title, "Keys · Home");
        assert!(rows.iter().any(|(k, _)| k == "f"));
        let s = screen(&a, 100, 30);
        save("keys-home", &s);
        assert!(s.contains("Alt+letter"), "{s}");
        a.key(key(KeyCode::Esc));
        assert!(a.overlays.is_empty());
        // F1 too, in a section
        a.key(key(KeyCode::Char('r')));
        a.key(key(KeyCode::F(1)));
        assert!(
            matches!(a.overlays.last(), Some(Overlay::Keys { title, .. }) if title == "Keys · Repair")
        );
        a.overlays.clear();
        a.screen = Screen::Home;
        // no letters on the tiles; the hint bar names the highlighted tile's shortcut
        a.home = HomeSel::Tile(2);
        let s = screen(&a, 100, 30);
        assert!(
            s.contains("shortcut V") && s.contains("? keys and help"),
            "{s}"
        );
        assert!(!s.contains("VECTOR 3"), "{s}");
        a.hover = Some(4);
        assert!(screen(&a, 100, 30).contains("shortcut S"));
        a.hover = None;
        // f does the suggested fix
        a.overview["suggestions"] = json!([{"text": "bromigOS on vda2 didn't finish starting last time", "action": "why", "device": "vda2"}]);
        let fx = a.key(key(KeyCode::Char('f')));
        assert!(
            fx.iter().any(
                |e| matches!(e, Effect::Call { args, .. } if args.join(" ") == "check last-boot")
            ),
            "{fx:?}"
        );
    }

    #[test]
    fn tools_cards_only_for_what_is_there_and_the_shell_toolbelt() {
        let mut a = app();
        a.key(key(KeyCode::Char('t')));
        let labels: Vec<_> = a.items().iter().map(|i| i.label).collect();
        for want in [
            "System monitor",
            "Processes",
            "GPUs",
            "Disk usage",
            "Temperatures",
            "Hardware report",
            "Files",
            "Find text",
            "Network test",
            "Speed test",
            "Neovim",
            "Micro",
            "Git",
            "Sessions",
            "Herdr",
            "Recover files",
            "Partitions",
        ] {
            assert!(labels.contains(&want), "{want}: {labels:?}");
        }
        // not on this (stand-in) system: no card
        for gone in [
            "Disk I/O",
            "Wi-Fi",
            "Firmware",
            "Stress test",
            "Power",
            "Partition table",
        ] {
            assert!(!labels.contains(&gone), "{gone}: {labels:?}");
        }
        // each runs with the screen handed over
        let fx = a.key(key(KeyCode::Enter));
        assert_eq!(fx, vec![Effect::Exec(vec!["btop".into()])]);
        for (name, look) in [("nerd", Look::wick()), ("console", console_look())] {
            a.look = look;
            a.look.motion = false;
            let s = screen(&a, 110, 34);
            assert!(s.contains("System monitor") && s.contains("btop"), "{s}");
            save(&format!("tools-{name}"), &s);
        }
        // the Shell's keys page: the toolbelt, grouped, a line each
        a.look = Look::wick();
        a.open_section(6);
        a.key(key(KeyCode::Char('?')));
        let Some(Overlay::Keys { rows, .. }) = a.overlays.last() else {
            panic!("{:?}", a.overlays)
        };
        for g in [
            "# Finding and reading",
            "# Network",
            "# Disks and files",
            "# System and debugging",
            "# Editing",
            "# Windows",
            "# Security",
        ] {
            assert!(rows.iter().any(|(k, _)| k == g), "{g}");
        }
        assert!(
            rows.iter()
                .any(|(_, w)| w.contains("tldr NAME for examples (works offline)"))
        );
        save("keys-shell", &screen(&a, 110, 34));
        // it scrolls
        for _ in 0..30 {
            a.key(key(KeyCode::Down));
        }
        let s = screen(&a, 110, 34);
        save("keys-shell-scrolled", &s);
        assert!(
            s.contains("DISKS AND FILES") || s.contains("SYSTEM AND DEBUGGING"),
            "{s}"
        );
    }

    /// The buffer's rows, and its problems: a wide glyph cut at the edge, or a panel's corner
    /// inside another panel (a border drawn over another panel's area).
    fn layout_problems(app: &App, w: u16, h: u16) -> (String, Vec<String>) {
        let mut t = Terminal::new(TestBackend::new(w, h)).unwrap();
        t.draw(|f| draw(f, app)).unwrap();
        let b = t.backend().buffer();
        let mut text = String::new();
        let mut bad = Vec::new();
        for y in 0..h {
            let mut row = String::new();
            let mut inside = false;
            for x in 0..w {
                let sym = b[(x, y)].symbol();
                row.push_str(sym);
                if x == w - 1 && unicode_width::UnicodeWidthStr::width(sym) > 1 {
                    bad.push(format!("row {y}: a wide glyph cut at the edge"));
                }
                // ASCII frames' corners are all "+": only the box-drawing ones are checked
                match sym {
                    "╭" | "╰" | "┏" | "┗" => {
                        if inside {
                            bad.push(format!("row {y} col {x}: a corner inside a panel"));
                        }
                        inside = true;
                    }
                    "╮" | "╯" | "┓" | "┛" => {
                        if !inside {
                            bad.push(format!("row {y} col {x}: a closing corner outside a panel"));
                        }
                        inside = false;
                    }
                    "│" | "┃" => inside = !inside,
                    _ => {}
                }
            }
            text.push_str(row.trim_end());
            text.push('\n');
        }
        (text, bad)
    }

    /// Every screen at every size, from a 4K terminal to a phone: nothing past the edge, no
    /// panel over another; under 40×15, the "make it bigger" screen.
    #[test]
    fn every_screen_at_every_size() {
        let sizes = [
            (200u16, 55u16),
            (150, 45),
            (120, 35),
            (80, 24),
            (60, 30),
            (40, 15),
        ];
        for (lname, look) in [("nerd", Look::wick()), ("console", console_look())] {
            let mut screens: Vec<(String, App)> = Vec::new();
            let mut a = app();
            a.look = look;
            a.look.motion = false;
            screens.push(("home".into(), {
                let mut h = app();
                h.look = a.look;
                h
            }));
            for (i, sec) in SECTIONS.iter().enumerate() {
                if *sec == "VECTOR" {
                    continue;
                }
                let mut x = app();
                x.look = a.look;
                let fx = x.open_section(i);
                drive(&mut x, fx);
                if *sec == "Lab" {
                    x.lab = lab_cards();
                }
                screens.push((sec.to_lowercase(), x));
            }
            let mut x = app();
            x.look = a.look;
            let fx = x.open_section(0);
            drive(&mut x, fx);
            let fx = x.choose(
                &section_items("Repair")
                    .into_iter()
                    .find(|i| i.act == Act::Black)
                    .unwrap(),
            );
            drive(&mut x, fx);
            screens.push(("finding".into(), x));
            let mut x = app();
            x.look = a.look;
            let fx = x.picked(Pick::EraseDisk, "/dev/sdb".into());
            drive(&mut x, fx);
            x.key(key(KeyCode::Enter));
            screens.push(("erase-confirm".into(), x));
            let mut x = app();
            x.look = a.look;
            x.open_section(6);
            x.key(key(KeyCode::Char('?')));
            screens.push(("keys-shell".into(), x));
            for (name, mut s) in screens {
                for (w, h) in sizes {
                    s.size = Rect::new(0, 0, w, h);
                    let (text, bad) = layout_problems(&s, w, h);
                    assert!(bad.is_empty(), "{name} {lname} at {w}x{h}: {bad:?}\n{text}");
                    if lname == "nerd"
                        && (name == "home" || name == "repair")
                        && [150, 110, 80, 60].contains(&w)
                    {
                        save(&format!("{name}-{w}"), &text);
                    }
                    if ["home", "repair", "lab", "finding"].contains(&name.as_str()) {
                        save(&format!("{name}-{lname}-{w}x{h}"), &text);
                    }
                }
                if lname == "nerd" && (name == "home" || name == "repair") {
                    s.size = Rect::new(0, 0, 110, 32);
                    save(&format!("{name}-110"), &layout_problems(&s, 110, 32).0);
                }
            }
        }
        // under 40×15: the "make it bigger" screen
        let a = app();
        let (text, _) = layout_problems(&a, 39, 12);
        assert!(text.contains("Make the window bigger"), "{text}");
    }

    /// On the Linux console (16 colours) the highlighted tile's and card's text must not be the
    /// colour of its surface (it was: green on green, the name invisible).
    #[test]
    fn console_selection_is_readable() {
        let mut a = app();
        a.look = console_look();
        for (setup, word) in [(0usize, "Repair"), (1, "System monitor")] {
            if setup == 1 {
                a.key(key(KeyCode::Char('t')));
            }
            let mut t = Terminal::new(TestBackend::new(100, 30)).unwrap();
            t.draw(|f| draw(f, &a)).unwrap();
            let b = t.backend().buffer();
            let mut found = false;
            for y in 0..30 {
                let row: String = (0..100).map(|x| b[(x, y)].symbol().to_string()).collect();
                if let Some(at) = row.find(word) {
                    let x0 = row[..at].chars().count() as u16;
                    for x in x0..x0 + word.len() as u16 {
                        let c = &b[(x, y)];
                        assert_ne!(
                            c.fg, c.bg,
                            "{word}: text and surface the same colour at {x},{y}"
                        );
                        assert!(
                            !c.modifier.contains(ratatui::style::Modifier::REVERSED),
                            "{word}: reversed"
                        );
                    }
                    found = true;
                    break;
                }
            }
            assert!(found, "{word} not drawn");
        }
        // and the icons are the console font's symbols, not letters standing in
        let s = screen(&a, 100, 30);
        assert!(!s.contains("\u{f0ad}"));
    }

    #[test]
    fn c_shows_a_findings_commands_and_writes_the_steps() {
        let mut a = app();
        let dir =
            std::env::temp_dir().join(format!("bromigos-fieldkit-steps-{}", std::process::id()));
        a.run_dir = dir.clone();
        let fx = a.open_section(0);
        drive(&mut a, fx);
        let i = a.items().iter().position(|i| i.act == Act::Black).unwrap();
        a.sel = i;
        let fx = a.key(key(KeyCode::Enter));
        drive(&mut a, fx);
        // the findings: the first fixable one is chosen; c shows its commands
        a.key(key(KeyCode::Char('c')));
        let Some(Overlay::Commands {
            commands,
            touches,
            cli,
            ..
        }) = a.overlays.last().cloned()
        else {
            panic!("{:?}", a.overlays)
        };
        assert_eq!(
            commands,
            vec![
                "mkdir -p /mnt/bromigos/var/lib/bromigos/fieldkit-backups/x/etc/sddm.conf.d",
                "mv /mnt/bromigos/etc/sddm.conf.d/10-gpu.conf.disabled /mnt/bromigos/var/lib/bromigos/fieldkit-backups/x/etc/sddm.conf.d/"
            ]
        );
        assert_eq!(touches, vec!["/etc/sddm.conf.d/10-gpu.conf.disabled"]);
        assert_eq!(cli, "bromigos fieldkit repair black-screen --dry-run");
        let s = screen(&a, 110, 34);
        save("commands", &s);
        assert!(
            s.contains("THE COMMANDS")
                && s.contains("WHAT IT TOUCHES")
                && s.contains("FROM THE COMMAND LINE"),
            "{s}"
        );
        // copy: OSC 52, and it says the console may not take it
        let fx = a.key(key(KeyCode::Enter));
        assert!(
            matches!(&fx[..], [Effect::Copy(t)] if t.starts_with("mkdir -p")),
            "{fx:?}"
        );
        assert!(
            matches!(a.overlays.last(), Some(Overlay::Commands { note, .. }) if note.contains("OSC 52"))
        );
        // step by step: the file, and a shell that offers each step
        a.key(key(KeyCode::Right));
        let fx = a.key(key(KeyCode::Enter));
        let [Effect::Exec(argv)] = &fx[..] else {
            panic!("{fx:?}")
        };
        assert_eq!(argv[0..2], ["bash".to_string(), "--rcfile".to_string()]);
        let steps = std::fs::read_to_string(dir.join("steps.sh")).unwrap();
        assert!(
            steps.starts_with("#!/bin/sh\n# bromigOS Field Kit: "),
            "{steps}"
        );
        assert!(
            steps.contains("# What it touches: /etc/sddm.conf.d/10-gpu.conf.disabled"),
            "{steps}"
        );
        assert!(steps.contains(
            "# The same from the command line: bromigos fieldkit repair black-screen --dry-run"
        ));
        assert!(steps.trim_end().ends_with("/etc/sddm.conf.d/"), "{steps}");
        let rc = std::fs::read_to_string(dir.join("steps.rc")).unwrap();
        let hist: Vec<&str> = rc.lines().filter(|l| l.starts_with("history -s")).collect();
        assert_eq!(hist.len(), 2);
        assert!(
            hist[1].contains("mkdir -p"),
            "the first step is the first Up: {hist:?}"
        );
        // the shell ends: the same screen, the same dialog, the same selection
        let before = (a.screen, a.section, a.sel, a.overlays.len());
        assert_eq!((a.screen, a.section, a.sel, a.overlays.len()), before);
        a.overlays.pop();
        assert!(matches!(
            a.overlays.last(),
            Some(Overlay::Findings { sel: 1, .. })
        ));
        // c on a section's action asks the engine for its plan; the hint says what it touches
        a.overlays.clear();
        let g = a.items().iter().position(|i| i.act == Act::Grub).unwrap();
        a.sel = g;
        let s = screen(&a, 160, 40);
        assert!(s.contains("touches: GRUB on the disk"), "{s}");
        let fx = a.key(key(KeyCode::Char('c')));
        assert!(
            matches!(&fx[..], [Effect::Call { args, .. }] if args.join(" ") == "plan grub-repair"),
            "{fx:?}"
        );
        drive(&mut a, fx);
        assert!(
            matches!(a.overlays.last(), Some(Overlay::Commands { commands, .. }) if commands.iter().any(|c| c.contains("grub-install")))
        );
        save("commands-plan", &screen(&a, 110, 34));
        // and a confirm dialog has a "Show the commands" button
        a.overlays.clear();
        let fx = a.key(key(KeyCode::Enter));
        assert!(fx.is_empty());
        let s = screen(&a, 110, 34);
        assert!(
            s.contains("Show the commands") && s.contains("It touches: GRUB"),
            "{s}"
        );
        let _ = std::fs::remove_dir_all(dir);
    }

    /// ~70 columns: "↓ more" sits on the panel's frame, never over a row; badges shorten so the
    /// labels stay whole.
    #[test]
    fn narrow_lists_keep_labels_and_put_more_on_the_frame() {
        let mut a = app();
        a.status["target"] = Value::Null; // nothing mounted: most repairs say "mount first"
        a.status["live"] = json!(true);
        let fx = a.open_section(0);
        drive(&mut a, fx);
        a.status["target"] = Value::Null;
        for (w, h) in [(70u16, 18u16), (60, 16)] {
            a.size = Rect::new(0, 0, w, h);
            let s = screen(&a, w, h);
            save(&format!("repair-narrow-{w}x{h}"), &s);
            assert!(
                s.contains("What went wrong on the last boot?"),
                "the label is whole at {w}:\n{s}"
            );
            let more: Vec<&str> = s.lines().filter(|l| l.contains("more")).collect();
            assert!(
                !more.is_empty(),
                "the list is longer than the panel at {w}x{h}:\n{s}"
            );
            for l in more {
                assert!(
                    l.trim_start().starts_with('╰') || l.trim_start().starts_with('╭'),
                    "on the frame, not a row: {l:?}\n{s}"
                );
            }
            assert!(
                !s.contains("mount your install first"),
                "the short form at {w}:\n{s}"
            );
        }
    }

    #[test]
    fn remote_help_shows_in_the_status_line() {
        let mut a = app();
        a.status["remote_words"] =
            json!("REMOTE HELP ON · ssh root@10.0.2.15 · password wick-orbit-amber-42");
        let f = facts(&a);
        assert!(
            f.iter()
                .any(|(_, v, t)| v.starts_with("REMOTE HELP ON") && *t == Tone::Warn)
        );
    }
}
