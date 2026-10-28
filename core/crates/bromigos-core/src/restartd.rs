//! What other packages restart after they upgrade: `restart.d` drop-ins, and the user
//! services still running a program an update replaced.
//!
//! A package installs `/usr/share/bromigos/restart.d/<name>.toml` to say what of its own
//! `bromigos update` (and `bromigos restart`) restarts once it's newer than what runs:
//!
//! ```toml
//! package = "brodec-desktop"          # optional; default: the file's name
//! [[unit]]                            # systemd --user units, restarted in this order
//! name = "brodecd.service"
//! # policy = "restart"                # the default; "notify" asks first
//! [[unit]]
//! name = "brodec-machine.service"
//! [[app]]
//! name = "BRODEC"
//! exe = "/usr/bin/brodec-desktop"
//! policy = "self"                     # it restarts itself; "notify" asks the user
//! ```
//!
//! A unit is stale when it has processes and its package was installed after the oldest
//! of them started, or one of them runs a program that was replaced (`/proc/<pid>/exe`
//! ends in ` (deleted)`). `restart` units are restarted with `systemctl --user
//! try-restart`, in the files' order (by file name) and each file's; `notify` units get a
//! desktop notification whose "Restart now" restarts them. An app is never stopped from
//! here: `self` is reported (the app restarts itself when it can), `notify` gets a
//! notification.
//!
//! Every other user service running a replaced program is found too, by the cgroup of
//! its processes, and only reported (`stale`): restarting what nobody declared could cut
//! off something in use.

use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::os::unix::fs::MetadataExt;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::update::{Installed, Need, Plan};

/// How a declared unit restarts.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum UnitPolicy {
    /// `systemctl --user try-restart`, without asking.
    #[default]
    Restart,
    /// A desktop notification asks first ("Restart now").
    Notify,
}

/// How a declared app restarts.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum AppPolicy {
    /// The app watches its own program and restarts itself when it can.
    #[serde(rename = "self")]
    Itself,
    /// A desktop notification tells the user to restart it.
    #[default]
    Notify,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Unit {
    pub name: String,
    #[serde(default)]
    pub policy: UnitPolicy,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct App {
    pub name: String,
    /// The program, an absolute path.
    pub exe: String,
    #[serde(default)]
    pub policy: AppPolicy,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct File {
    package: Option<String>,
    #[serde(default, rename = "unit")]
    units: Vec<Unit>,
    #[serde(default, rename = "app")]
    apps: Vec<App>,
}

/// One drop-in, read.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Declared {
    pub file: PathBuf,
    /// The package whose install date says whether they're stale.
    pub package: String,
    pub units: Vec<Unit>,
    pub apps: Vec<App>,
}

/// The unit types a drop-in may name.
const UNIT_TYPES: [&str; 3] = [".service", ".socket", ".timer"];

/// A systemd unit name: its characters (`A-Za-z0-9:_.\-@`), at most 255, a name before
/// a known type, and nothing a shell or systemctl would read as an option.
pub fn valid_unit(name: &str) -> bool {
    name.len() <= 255
        && !name.starts_with('-')
        && UNIT_TYPES
            .iter()
            .any(|t| name.strip_suffix(t).is_some_and(|stem| !stem.is_empty()))
        && name
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || ":_.\\-@".contains(c))
}

/// A drop-in's text, `stem` its file's name without `.toml`.
pub fn parse(file: &Path, stem: &str, text: &str) -> Result<Declared, String> {
    let f: File = toml::from_str(text).map_err(|e| e.message().to_owned())?;
    for u in &f.units {
        if !valid_unit(&u.name) {
            return Err(format!("not a unit name: {:?}", u.name));
        }
    }
    for a in &f.apps {
        if a.name.trim().is_empty() {
            return Err("an app without a name".to_owned());
        }
        if !a.exe.starts_with('/') {
            return Err(format!("{}: exe must be an absolute path", a.name));
        }
    }
    let package = f.package.unwrap_or_else(|| stem.to_owned());
    if package.is_empty() {
        return Err("no package".to_owned());
    }
    Ok(Declared {
        file: file.to_path_buf(),
        package,
        units: f.units,
        apps: f.apps,
    })
}

/// Every drop-in in `dir`, by file name, and what's wrong with those that don't read
/// (left out, not fatal).
pub fn load(dir: &Path) -> (Vec<Declared>, Vec<String>) {
    let mut files: Vec<PathBuf> = fs::read_dir(dir)
        .into_iter()
        .flatten()
        .flatten()
        .map(|e| e.path())
        .filter(|p| p.extension().is_some_and(|x| x == "toml"))
        .collect();
    files.sort();
    let (mut ok, mut bad) = (vec![], vec![]);
    for p in files {
        let stem = p.file_stem().and_then(|s| s.to_str()).unwrap_or_default();
        match fs::read_to_string(&p)
            .map_err(|e| e.to_string())
            .and_then(|t| parse(&p, stem, &t))
        {
            Ok(d) => ok.push(d),
            Err(e) => bad.push(format!("{}: {e}", p.display())),
        }
    }
    (ok, bad)
}

// ------------------------------------------------------------------ processes

/// One of this user's processes, as far as restarts go.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Proc {
    pub pid: i32,
    /// Its systemd --user service (None: a scope, or outside the user's manager).
    pub unit: Option<String>,
    /// Its program's path (without ` (deleted)`).
    pub exe: Option<String>,
    /// The program was replaced or removed after it started.
    pub deleted: bool,
    /// When it started (Unix seconds).
    pub started: Option<i64>,
}

/// The user service a process runs in, from `/proc/<pid>/cgroup`: the first `*.service`
/// under `user@<uid>.service/` (`0::/user.slice/user-1000.slice/user@1000.service/
/// app.slice/brodecd.service` -> `brodecd.service`).
pub fn unit_of(cgroup: &str, uid: u32) -> Option<String> {
    let manager = format!("user@{uid}.service");
    cgroup.lines().find_map(|l| {
        // hierarchy-ID:controllers:path; a unit name may hold a ':' itself
        let path = l.splitn(3, ':').nth(2)?;
        let mut parts = path.split('/').skip_while(|p| *p != manager).skip(1);
        parts
            .find(|p| p.ends_with(".service"))
            .filter(|u| valid_unit(u))
            .map(str::to_owned)
    })
}

/// A `/proc/<pid>/exe` link: the program's path, and whether it was replaced.
pub fn exe_of(link: &str) -> (String, bool) {
    match link.strip_suffix(" (deleted)") {
        Some(p) => (p.to_owned(), true),
        None => (link.to_owned(), false),
    }
}

/// `uid`'s live processes under `proc` (zombies, and this process, left out).
pub fn procs(proc: &Path, uid: u32) -> Vec<Proc> {
    let me = std::process::id() as i32;
    let btime = crate::update::boot_time(proc).unwrap_or(0);
    let mut out: Vec<Proc> = fs::read_dir(proc)
        .into_iter()
        .flatten()
        .flatten()
        .filter_map(|e| {
            let pid: i32 = e.file_name().to_str()?.parse().ok()?;
            if pid == me || e.metadata().ok()?.uid() != uid {
                return None;
            }
            let dir = e.path();
            let stat = fs::read_to_string(dir.join("stat")).ok()?;
            if stat
                .rsplit_once(") ")
                .is_none_or(|(_, r)| r.starts_with('Z'))
            {
                return None;
            }
            let exe = fs::read_link(dir.join("exe"))
                .ok()
                .and_then(|l| l.to_str().map(exe_of));
            Some(Proc {
                pid,
                unit: fs::read_to_string(dir.join("cgroup"))
                    .ok()
                    .and_then(|c| unit_of(&c, uid)),
                deleted: exe.as_ref().is_some_and(|e| e.1),
                exe: exe.map(|e| e.0),
                started: crate::update::proc_start(proc, pid, btime),
            })
        })
        .collect();
    out.sort_by_key(|p| p.pid);
    out
}

// ------------------------------------------------------------------ the plan

/// Why a group of processes is stale: its package is newer, or its program was replaced.
fn stale_why(ps: &[&Proc], package: &str, inst: &BTreeMap<String, Installed>) -> Option<String> {
    let started = ps.iter().filter_map(|p| p.started).min();
    if let Some(i) = inst.get(package)
        && started.is_some_and(|s| i.installed > s)
    {
        return Some(format!(
            "{package} {} is newer than the running process",
            i.version
        ));
    }
    ps.iter().find(|p| p.deleted).map(|p| match &p.exe {
        Some(e) => format!("its program {e} was replaced"),
        None => "its program was replaced".to_owned(),
    })
}

fn pids(ps: &[&Proc]) -> Vec<i32> {
    ps.iter().map(|p| p.pid).collect()
}

/// What the declared units and apps need, in the drop-ins' order (units before apps in
/// each), then every other user service running a replaced program (`stale`, reported
/// only). `pieces`: the pids of bromigOS's own pieces, which restart their own way; a
/// service holding one of them is left to them.
pub fn plan(
    declared: &[Declared],
    procs: &[Proc],
    inst: &BTreeMap<String, Installed>,
    pieces: &BTreeSet<i32>,
) -> Vec<Plan> {
    let mut out = Vec::new();
    let mut units: BTreeSet<&str> = BTreeSet::new();
    let mut apps: BTreeSet<i32> = BTreeSet::new();
    for d in declared {
        for u in &d.units {
            units.insert(&u.name);
            let ps: Vec<&Proc> = procs
                .iter()
                .filter(|p| p.unit.as_deref() == Some(u.name.as_str()))
                .collect();
            if ps.is_empty() {
                continue;
            }
            let Some(why) = stale_why(&ps, &d.package, inst) else {
                continue;
            };
            out.push(Plan {
                what: u.name.clone(),
                need: match u.policy {
                    UnitPolicy::Restart => Need::Restart,
                    UnitPolicy::Notify => Need::Notify,
                },
                why,
                pids: pids(&ps),
                unit: Some(u.name.clone()),
                package: Some(d.package.clone()),
            });
        }
        for a in &d.apps {
            let ps: Vec<&Proc> = procs
                .iter()
                .filter(|p| p.exe.as_deref() == Some(a.exe.as_str()))
                .collect();
            apps.extend(ps.iter().map(|p| p.pid));
            if ps.is_empty() {
                continue;
            }
            let Some(why) = stale_why(&ps, &d.package, inst) else {
                continue;
            };
            out.push(Plan {
                what: a.name.clone(),
                need: match a.policy {
                    AppPolicy::Itself => Need::Itself,
                    AppPolicy::Notify => Need::Notify,
                },
                why,
                pids: pids(&ps),
                unit: None,
                package: Some(d.package.clone()),
            });
        }
    }
    // every other user service with a replaced program: by unit, in name order
    let mut by_unit: BTreeMap<&str, Vec<&Proc>> = BTreeMap::new();
    for p in procs {
        if let Some(u) = p.unit.as_deref() {
            by_unit.entry(u).or_default().push(p);
        }
    }
    for (u, ps) in by_unit {
        if units.contains(u) || ps.iter().any(|p| pieces.contains(&p.pid)) {
            continue;
        }
        let replaced: Vec<&Proc> = ps
            .into_iter()
            .filter(|p| p.deleted && !apps.contains(&p.pid))
            .collect();
        if replaced.is_empty() {
            continue;
        }
        let mut exes: Vec<&str> = replaced.iter().filter_map(|p| p.exe.as_deref()).collect();
        exes.dedup();
        out.push(Plan {
            what: u.to_owned(),
            need: Need::Stale,
            why: match exes.is_empty() {
                true => "runs a program that was replaced".to_owned(),
                false => format!("runs a program that was replaced: {}", exes.join(", ")),
            },
            pids: pids(&replaced),
            unit: Some(u.to_owned()),
            package: None,
        });
    }
    out
}

/// The declared unit a name means (`brodecd` or `brodecd.service`), for `bromigos restart
/// NAME`.
pub fn find_unit<'a>(declared: &'a [Declared], name: &str) -> Option<(&'a Declared, &'a Unit)> {
    declared.iter().find_map(|d| {
        d.units
            .iter()
            .find(|u| u.name == name || u.name == format!("{name}.service"))
            .map(|u| (d, u))
    })
}

/// The named declared units, restarted whether stale or not (`bromigos restart NAME`).
pub fn plan_named(declared: &[Declared], procs: &[Proc], names: &[String]) -> Vec<Plan> {
    names
        .iter()
        .filter_map(|n| find_unit(declared, n))
        .map(|(d, u)| Plan {
            what: u.name.clone(),
            need: Need::Restart,
            why: "asked for".to_owned(),
            pids: procs
                .iter()
                .filter(|p| p.unit.as_deref() == Some(u.name.as_str()))
                .map(|p| p.pid)
                .collect(),
            unit: Some(u.name.clone()),
            package: Some(d.package.clone()),
        })
        .collect()
}

// ------------------------------------------------------------------ doing it

/// The shell line behind a "Restart now" notification: the title, body and unit come in
/// as its positional parameters, never as part of the line.
pub const NOTIFY_RESTART_SH: &str = r#"a=$(notify-send -a bromigos -u normal -i system-software-update -A restart="Restart now" "$1" "$2") && [ "$a" = restart ] && exec systemctl --user restart -- "$3""#;

/// The notification's title and body for a plan that asks first.
pub fn notice(plan: &Plan) -> (String, String) {
    let package = plan.package.as_deref().unwrap_or(&plan.what);
    match &plan.unit {
        Some(u) => (
            format!("{package} updated — restart now?"),
            format!("{u} still runs the old version ({}).", plan.why),
        ),
        None => (
            format!("{} updated", plan.what),
            format!(
                "Quit {} and open it again to run the new version.",
                plan.what
            ),
        ),
    }
}

/// The argument vector for a plan's action: `systemctl --user try-restart` for a unit to
/// restart, the detached notification for one that asks first, plain `notify-send` for an
/// app (nothing of it is stopped). None: nothing to run.
pub fn command(plan: &Plan) -> Option<Vec<String>> {
    let s = |x: &str| x.to_owned();
    match (plan.need, plan.unit.as_deref()) {
        (Need::Restart, Some(u)) if valid_unit(u) => Some(vec![
            s("systemctl"),
            s("--user"),
            s("try-restart"),
            s("--"),
            s(u),
        ]),
        (Need::Notify, Some(u)) if valid_unit(u) => {
            let (title, body) = notice(plan);
            Some(vec![
                s("setsid"),
                s("-f"),
                s("sh"),
                s("-c"),
                s(NOTIFY_RESTART_SH),
                s("sh"),
                title,
                body,
                s(u),
            ])
        }
        (Need::Notify, None) => {
            let (title, body) = notice(plan);
            Some(vec![
                s("notify-send"),
                s("-a"),
                s("bromigos"),
                s("-u"),
                s("normal"),
                s("-i"),
                s("system-software-update"),
                title,
                body,
            ])
        }
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const BRODEC: &str = r#"
package = "brodec-desktop"
[[unit]]
name = "brodecd.service"
[[unit]]
name = "brodec-machine.service"
[[app]]
name = "BRODEC"
exe = "/usr/bin/brodec-desktop"
policy = "self"
"#;

    fn decl(text: &str) -> Declared {
        parse(Path::new("/x/brodec.toml"), "brodec", text).unwrap()
    }

    fn inst(v: &str, t: i64) -> Installed {
        Installed {
            version: v.into(),
            installed: t,
        }
    }

    fn proc(pid: i32, unit: Option<&str>, exe: &str, deleted: bool, started: i64) -> Proc {
        Proc {
            pid,
            unit: unit.map(str::to_owned),
            exe: Some(exe.to_owned()),
            deleted,
            started: Some(started),
        }
    }

    #[test]
    fn drop_ins_read_and_bad_ones_are_said() {
        let d = decl(BRODEC);
        assert_eq!(d.package, "brodec-desktop");
        assert_eq!(
            d.units.iter().map(|u| u.name.as_str()).collect::<Vec<_>>(),
            ["brodecd.service", "brodec-machine.service"]
        );
        assert_eq!(d.units[0].policy, UnitPolicy::Restart);
        assert_eq!(d.apps[0].policy, AppPolicy::Itself);
        // the package defaults to the file's name; an app's policy to notify
        let d = parse(
            Path::new("/x/foo.toml"),
            "foo",
            "[[unit]]\nname = \"foo.service\"\npolicy = \"notify\"\n[[app]]\nname = \"Foo\"\nexe = \"/usr/bin/foo\"\n",
        )
        .unwrap();
        assert_eq!(d.package, "foo");
        assert_eq!(d.units[0].policy, UnitPolicy::Notify);
        assert_eq!(d.apps[0].policy, AppPolicy::Notify);
        let p = Path::new("/x/f.toml");
        for bad in [
            "[[unit]]\nname = \"a.service\"\nwhen = \"now\"\n", // unknown field
            "colour = \"red\"\n",                               // unknown top-level key
            "[[unit]]\nname = \"a b.service\"\n",               // not a unit name
            "[[unit]]\nname = \"$(reboot).service\"\n",
            "[[unit]]\nname = \"brodecd\"\n", // no type
            "[[unit]]\nname = \"-x.service\"\n",
            "[[unit]]\nname = \"a.service\"\npolicy = \"kill\"\n",
            "[[app]]\nname = \"A\"\nexe = \"a\"\n", // relative
            "[[app]]\nname = \"A\"\nexe = \"/a\"\npolicy = \"restart\"\n",
            "package = \n",
        ] {
            assert!(parse(p, "f", bad).is_err(), "{bad}");
        }
    }

    #[test]
    fn load_reads_in_name_order_and_keeps_going() {
        let dir = tempfile::tempdir().unwrap();
        fs::write(
            dir.path().join("b.toml"),
            "[[unit]]\nname = \"b.service\"\n",
        )
        .unwrap();
        fs::write(
            dir.path().join("a.toml"),
            "[[unit]]\nname = \"a.service\"\n",
        )
        .unwrap();
        fs::write(dir.path().join("c.toml"), "nonsense = 1\n").unwrap();
        fs::write(dir.path().join("README"), "not a drop-in").unwrap();
        let (ok, bad) = load(dir.path());
        assert_eq!(
            ok.iter().map(|d| d.package.as_str()).collect::<Vec<_>>(),
            ["a", "b"]
        );
        assert_eq!(bad.len(), 1);
        assert!(bad[0].contains("c.toml"), "{bad:?}");
        assert!(load(&dir.path().join("missing")).0.is_empty());
    }

    #[test]
    fn unit_names() {
        for ok in [
            "brodecd.service",
            "dbus-:1.2-ai.brodec.Desktop@0.service",
            "app-Hyprland-kitty@abc.service",
            "a.timer",
            "x\\x2d.socket",
        ] {
            assert!(valid_unit(ok), "{ok}");
        }
        for bad in [
            "",
            ".service",
            "a.scope",
            "a",
            "a;b.service",
            "a/b.service",
            "--now.service",
        ] {
            assert!(!valid_unit(bad), "{bad}");
        }
    }

    #[test]
    fn a_process_maps_to_its_user_service_by_cgroup() {
        let cg = "0::/user.slice/user-1000.slice/user@1000.service/app.slice/brodecd.service\n";
        assert_eq!(unit_of(cg, 1000).as_deref(), Some("brodecd.service"));
        // a service's own sub-cgroup still counts as the service
        let cg = "0::/user.slice/user-1000.slice/user@1000.service/app.slice/foo.service/sub\n";
        assert_eq!(unit_of(cg, 1000).as_deref(), Some("foo.service"));
        // a unit name holding ':' (D-Bus activated, dbus-broker)
        let cg = "0::/user.slice/user-1000.slice/user@1000.service/app.slice/dbus-:1.2-ai.brodec.Desktop@0.service\n";
        assert_eq!(
            unit_of(cg, 1000).as_deref(),
            Some("dbus-:1.2-ai.brodec.Desktop@0.service")
        );
        // the hybrid hierarchy's named line
        let cg =
            "1:name=systemd:/user.slice/user-1000.slice/user@1000.service/pipewire.service\n0::/\n";
        assert_eq!(unit_of(cg, 1000).as_deref(), Some("pipewire.service"));
        // scopes, the manager itself, the system's services, another user's
        for none in [
            "0::/user.slice/user-1000.slice/user@1000.service/app.slice/app-kitty-1.scope\n",
            "0::/user.slice/user-1000.slice/user@1000.service/init.scope\n",
            "0::/system.slice/sshd.service\n",
            "0::/user.slice/user-1001.slice/user@1001.service/app.slice/x.service\n",
            "0::/user.slice/user-1000.slice/session-2.scope\n",
        ] {
            assert_eq!(unit_of(none, 1000), None, "{none}");
        }
    }

    #[test]
    fn a_replaced_program_shows_in_its_exe_link() {
        assert_eq!(
            exe_of("/usr/bin/brodecd (deleted)"),
            ("/usr/bin/brodecd".to_owned(), true)
        );
        assert_eq!(
            exe_of("/usr/bin/brodecd"),
            ("/usr/bin/brodecd".to_owned(), false)
        );
    }

    #[test]
    fn procs_reads_a_proc_tree() {
        use std::os::unix::fs::symlink;
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path();
        let uid = rustix::process::getuid().as_raw();
        fs::write(root.join("stat"), "cpu 1 2\nbtime 1000\n").unwrap();
        let mk = |pid: i32, state: &str, cgroup: &str, exe: &str| {
            let d = root.join(pid.to_string());
            fs::create_dir(&d).unwrap();
            // starttime (the 22nd field) 500 ticks: 5 s after boot
            fs::write(
                d.join("stat"),
                format!("{pid} (x) {state} 1 1 1 0 0 0 0 0 0 0 0 0 0 0 0 0 1 0 500 0\n"),
            )
            .unwrap();
            fs::write(d.join("cgroup"), cgroup).unwrap();
            symlink(exe, d.join("exe")).unwrap();
        };
        let svc =
            |u: &str| format!("0::/user.slice/user-{uid}.slice/user@{uid}.service/app.slice/{u}\n");
        mk(
            10,
            "S",
            &svc("brodecd.service"),
            "/usr/bin/brodecd (deleted)",
        );
        mk(11, "S", &svc("app-x.scope"), "/usr/bin/kitty");
        mk(12, "Z", &svc("brodecd.service"), "/usr/bin/brodecd");
        fs::create_dir(root.join("self")).unwrap();
        let ps = procs(root, uid);
        assert_eq!(
            ps,
            vec![
                proc(10, Some("brodecd.service"), "/usr/bin/brodecd", true, 1005),
                proc(11, None, "/usr/bin/kitty", false, 1005),
            ]
        );
    }

    #[test]
    fn declared_units_restart_when_their_package_is_newer_or_their_program_replaced() {
        let d = [decl(BRODEC)];
        let i = BTreeMap::from([("brodec-desktop".to_owned(), inst("0.2-1", 200))]);
        let none = BTreeSet::new();
        // started before the package: both units restart, in the file's order
        let ps = [
            proc(
                30,
                Some("brodec-machine.service"),
                "/usr/bin/brodec-machine",
                false,
                100,
            ),
            proc(20, Some("brodecd.service"), "/usr/bin/brodecd", false, 100),
        ];
        let p = plan(&d, &ps, &i, &none);
        let got: Vec<_> = p.iter().map(|p| (p.what.as_str(), p.need)).collect();
        assert_eq!(
            got,
            [
                ("brodecd.service", Need::Restart),
                ("brodec-machine.service", Need::Restart)
            ]
        );
        assert_eq!(p[0].unit.as_deref(), Some("brodecd.service"));
        assert_eq!(p[0].package.as_deref(), Some("brodec-desktop"));
        assert_eq!(
            p[0].why,
            "brodec-desktop 0.2-1 is newer than the running process"
        );
        // started after it: nothing
        let ps = [proc(
            20,
            Some("brodecd.service"),
            "/usr/bin/brodecd",
            false,
            300,
        )];
        assert!(plan(&d, &ps, &i, &none).is_empty());
        // started after it, but its program was replaced since (a reinstall, no new date)
        let ps = [proc(
            20,
            Some("brodecd.service"),
            "/usr/bin/brodecd",
            true,
            300,
        )];
        let p = plan(&d, &ps, &i, &none);
        assert_eq!(p.len(), 1);
        assert_eq!(p[0].why, "its program /usr/bin/brodecd was replaced");
        // not running: nothing to restart
        assert!(plan(&d, &[], &i, &none).is_empty());
    }

    #[test]
    fn notify_units_ask_and_apps_are_never_stopped() {
        let d = [decl(
            "package = \"foo\"\n[[unit]]\nname = \"foo.service\"\npolicy = \"notify\"\n\
             [[app]]\nname = \"Foo\"\nexe = \"/usr/bin/foo\"\n\
             [[app]]\nname = \"Bar\"\nexe = \"/usr/bin/bar\"\npolicy = \"self\"\n",
        )];
        let i = BTreeMap::from([("foo".to_owned(), inst("2", 200))]);
        let ps = [
            proc(1, Some("foo.service"), "/usr/bin/food", false, 100),
            proc(2, None, "/usr/bin/foo", true, 100),
            proc(
                3,
                Some("dbus-:1.4-org.bar@0.service"),
                "/usr/bin/bar",
                true,
                300,
            ),
        ];
        let p = plan(&d, &ps, &i, &BTreeSet::new());
        let got: Vec<_> = p.iter().map(|p| (p.what.as_str(), p.need)).collect();
        // Bar's D-Bus service isn't reported as a stale service: it's the declared app's
        assert_eq!(
            got,
            [
                ("foo.service", Need::Notify),
                ("Foo", Need::Notify),
                ("Bar", Need::Itself)
            ]
        );
        // the unit asks through a detached notification; the unit name is an argument
        let c = command(&p[0]).unwrap();
        assert_eq!(&c[..5], ["setsid", "-f", "sh", "-c", NOTIFY_RESTART_SH]);
        assert_eq!(c[6], "foo updated — restart now?");
        assert_eq!(c[8], "foo.service");
        assert!(!NOTIFY_RESTART_SH.contains("foo"));
        // the app: a notification, nothing killed
        let c = command(&p[1]).unwrap();
        assert_eq!(c[0], "notify-send");
        assert_eq!(c[7], "Foo updated");
        // self: nothing run from here
        assert_eq!(command(&p[2]), None);
    }

    #[test]
    fn a_restart_is_a_try_restart() {
        let d = [decl(BRODEC)];
        let i = BTreeMap::from([("brodec-desktop".to_owned(), inst("2", 200))]);
        let ps = [proc(
            20,
            Some("brodecd.service"),
            "/usr/bin/brodecd",
            false,
            100,
        )];
        let p = plan(&d, &ps, &i, &BTreeSet::new());
        assert_eq!(
            command(&p[0]).unwrap(),
            [
                "systemctl",
                "--user",
                "try-restart",
                "--",
                "brodecd.service"
            ]
        );
    }

    #[test]
    fn other_services_with_a_replaced_program_are_only_reported() {
        let d = [decl(BRODEC)];
        let i = BTreeMap::new();
        let ps = [
            proc(5, Some("pipewire.service"), "/usr/bin/pipewire", true, 100),
            proc(6, Some("pipewire.service"), "/usr/bin/pipewire", true, 100),
            proc(
                7,
                Some("wireplumber.service"),
                "/usr/bin/wireplumber",
                false,
                100,
            ),
            // a piece's service: the piece restarts it its own way
            proc(8, Some("waybar.service"), "/usr/bin/waybar", true, 100),
            // the declared app, D-Bus activated into a service of its own
            proc(
                9,
                Some("dbus.service"),
                "/usr/bin/brodec-desktop",
                true,
                100,
            ),
            proc(10, Some("dbus.service"), "/usr/bin/dbus-broker", false, 100),
            // not in a service
            proc(11, None, "/usr/bin/zsh", true, 100),
        ];
        let p = plan(&d, &ps, &i, &BTreeSet::from([8]));
        let got: Vec<_> = p.iter().map(|p| (p.what.as_str(), p.need)).collect();
        assert_eq!(
            got,
            [("BRODEC", Need::Itself), ("pipewire.service", Need::Stale)]
        );
        assert_eq!(p[1].pids, [5, 6]);
        assert_eq!(
            p[1].why,
            "runs a program that was replaced: /usr/bin/pipewire"
        );
        assert_eq!(command(&p[1]), None, "never restarted from here");
        // a declared unit is never reported as merely stale
        let ps = [proc(
            20,
            Some("brodecd.service"),
            "/usr/bin/brodecd",
            false,
            100,
        )];
        assert!(plan(&d, &ps, &i, &BTreeSet::new()).is_empty());
    }

    #[test]
    fn restart_names_a_declared_unit_with_or_without_its_type() {
        let d = [decl(BRODEC)];
        let ps = [proc(
            20,
            Some("brodecd.service"),
            "/usr/bin/brodecd",
            false,
            100,
        )];
        let p = plan_named(
            &d,
            &ps,
            &["brodecd".into(), "brodec-machine.service".into()],
        );
        let got: Vec<_> = p
            .iter()
            .map(|p| (p.what.as_str(), p.pids.clone()))
            .collect();
        assert_eq!(
            got,
            [
                ("brodecd.service", vec![20]),
                ("brodec-machine.service", vec![])
            ]
        );
        assert!(
            p.iter()
                .all(|p| p.need == Need::Restart && p.why == "asked for")
        );
        assert!(find_unit(&d, "nope").is_none());
    }
}
