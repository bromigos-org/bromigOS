//! `bromigos idle`: the idle policy (docs/idle.md). When the screensaver starts, the screen
//! locks, the displays go off and the machine suspends, from `~/.config/bromigos/idle.toml`
//! over the packaged defaults; presets; stay awake for a while. Every change renders the
//! hypridle config again and restarts this session's hypridle (bromigos_core::idle).

use anyhow::Result;
use bromigos_core::idle::{self, Status};
use bromigos_core::paths::Paths;
use clap::{Args, Subcommand};
use serde_json::{Value, json};

use crate::SCHEMA;

#[derive(Args)]
pub struct IdleArgs {
    /// Print the JSON document (schema in core/README.md)
    #[arg(long, global = true)]
    json: bool,
    /// Write and render only: don't restart hypridle
    #[arg(long, global = true)]
    no_restart: bool,
    #[command(subcommand)]
    cmd: Option<IdleCmd>,
}

#[derive(Subcommand)]
enum IdleCmd {
    /// The policy in force, in plain words, with any warnings (the default)
    Status,
    /// Change it: KEY VALUE pairs. screensaver|lock|displays|suspend on|off|MINUTES (a time
    /// also turns it on: 8, 90m, 1h), activity on|off|SECONDS, lock-before-sleep on|off, or
    /// any section.key of idle.toml
    Set {
        #[arg(required = true, num_args = 2.., value_name = "KEY VALUE")]
        pairs: Vec<String>,
    },
    /// A preset: default (bromigOS's timers), screensaver-only (the screensaver at its time,
    /// nothing locks, dims or sleeps), presentation (nothing idles)
    Preset { name: String },
    /// Stay awake for a while: 1h, 2h, 30m, 90 (minutes) or until-off; `off` ends it;
    /// `toggle [TIME]` turns it off when on, else on (1 h)
    StayAwake {
        #[arg(value_name = "TIME|until-off|off|toggle")]
        duration: String,
        /// toggle: how long when it turns on (default 1h)
        #[arg(value_name = "TIME")]
        time: Option<String>,
    },
    /// Stop staying awake (stay-awake off)
    Off,
    /// Put idle.toml back as it was before the last change (again: redo)
    Undo,
    /// Render the policy and restart this session's hypridle
    Apply,
    /// Point ~/.config/hypr/hypridle.conf at the rendered policy, keeping your own
    /// listeners (an update's migration runs it)
    Hook,
    /// Print the hypridle config the policy renders to
    Render {
        /// The packaged defaults' config instead of yours
        #[arg(long)]
        defaults: bool,
    },
    /// Hyprland's autostart: render the policy, then run hypridle (--detach: start it in
    /// this session now, through the compositor, unless it runs already)
    Start {
        #[arg(long)]
        detach: bool,
    },
}

fn doc(st: &Status) -> Value {
    let mut v = serde_json::to_value(st).unwrap_or(Value::Null);
    if let Value::Object(m) = &mut v {
        m.insert("schema".into(), json!(SCHEMA));
    }
    v
}

fn onoff(b: bool) -> &'static str {
    if b { "on" } else { "off" }
}

fn print_status(st: &Status) {
    let p = &st.policy;
    let mark = |k: &str| {
        if st.set.iter().any(|s| s == k) {
            "*"
        } else {
            " "
        }
    };
    println!("{}", st.summary);
    let row = |name: &str, on: bool, value: String, ek: &str, vk: &str| {
        println!(
            "  {name:<18} {}{:<4} {}{value}",
            mark(ek),
            onoff(on),
            mark(vk)
        );
    };
    row(
        "screensaver",
        p.screensaver.enabled,
        format!("{} min", p.screensaver.minutes),
        "screensaver.enabled",
        "screensaver.minutes",
    );
    row(
        "lock",
        p.lock.enabled,
        format!("{} min", p.lock.minutes),
        "lock.enabled",
        "lock.minutes",
    );
    row(
        "displays off",
        p.displays.enabled,
        format!("{} min", p.displays.minutes),
        "displays.enabled",
        "displays.minutes",
    );
    row(
        "suspend",
        p.suspend.enabled,
        format!("{} min", p.suspend.minutes),
        "suspend.enabled",
        "suspend.minutes",
    );
    println!(
        "  {:<18} {}{}",
        "lock before sleep",
        mark("sleep.lock_before"),
        onoff(p.lock_before_sleep)
    );
    row(
        "creatures doze",
        p.activity.enabled,
        format!("{} s", p.activity.seconds),
        "activity.enabled",
        "activity.seconds",
    );
    let awake = if st.stay_awake.on {
        match st.stay_awake.remaining_s {
            Some(r) => format!("on, {} min left", (r + 59) / 60),
            None => "on, until turned off".into(),
        }
    } else {
        "off".into()
    };
    let daemon = if st.hypridle.running {
        format!(
            "running ({})",
            st.hypridle
                .pids
                .iter()
                .map(|p| p.to_string())
                .collect::<Vec<_>>()
                .join(", ")
        )
    } else {
        "not running".into()
    };
    println!(
        "preset: {} · stay awake: {awake} · hypridle: {daemon}",
        st.preset.unwrap_or("custom")
    );
    if st.exists {
        println!(
            "yours: {} (* = set there; the rest are the defaults)",
            st.file.display()
        );
    } else {
        println!(
            "yours: none yet ({}); the defaults apply",
            st.file.display()
        );
    }
    for i in &st.inhibitors {
        println!("also keeping it awake: {} ({})", i.who, i.why);
    }
    for w in &st.warnings {
        println!("{}: {}", w.level, w.text);
    }
}

fn print_applied(a: &idle::Applied) {
    if a.restarts.is_empty() {
        println!("hypridle: not running in this session; the policy applies when it starts");
    }
    for d in &a.restarts {
        match &d.detail {
            Some(x) if !d.ok => println!("hypridle: {} FAILED: {x}", d.action),
            _ => println!("hypridle: {}", d.action),
        }
    }
}

/// Writes, renders and (unless asked not to) restarts; then says where things stand.
fn finish(paths: &Paths, a: &IdleArgs) -> Result<i32> {
    let applied = if a.no_restart {
        idle::render_file(paths).map_err(anyhow::Error::msg)?;
        None
    } else {
        Some(idle::apply(paths).map_err(anyhow::Error::msg)?)
    };
    let st = idle::status(paths);
    let ok = applied
        .as_ref()
        .is_none_or(|x| x.restarts.iter().all(|d| d.ok));
    if a.json {
        let mut v = doc(&st);
        v["applied"] = serde_json::to_value(&applied).unwrap_or(Value::Null);
        println!("{v}");
    } else {
        print_status(&st);
        if let Some(x) = &applied {
            print_applied(x);
        }
    }
    Ok(if ok { 0 } else { 1 })
}

fn refuse(a: &IdleArgs, e: String) -> Result<i32> {
    if a.json {
        println!("{}", json!({"schema": SCHEMA, "ok": false, "error": e}));
    } else {
        eprintln!("bromigos idle: {e}");
    }
    Ok(1)
}

fn awake_doc(paths: &Paths, a: &IdleArgs) -> Result<i32> {
    let st = idle::status(paths);
    if a.json {
        println!("{}", doc(&st));
    } else {
        let s = &st.stay_awake;
        match (s.on, s.until_local.as_deref()) {
            (true, Some(t)) => println!(
                "staying awake until {} ({} min left)",
                &t[11..16],
                (s.remaining_s.unwrap_or(0) + 59) / 60
            ),
            (true, None) => println!("staying awake until turned off (bromigos idle off)"),
            _ => println!("stay awake: off. {}", st.summary),
        }
    }
    Ok(0)
}

pub fn idle_cmd(paths: &Paths, a: IdleArgs) -> Result<i32> {
    match &a.cmd {
        None | Some(IdleCmd::Status) => {
            let st = idle::status(paths);
            if a.json {
                println!("{}", doc(&st));
            } else {
                print_status(&st);
            }
            Ok(0)
        }
        Some(IdleCmd::Set { pairs }) => {
            if pairs.len() % 2 != 0 {
                eprintln!("bromigos idle set KEY VALUE [KEY VALUE …]");
                return Ok(2);
            }
            let mut changes = Vec::new();
            for kv in pairs.chunks(2) {
                match idle::parse_set(&kv[0], &kv[1]) {
                    Ok(c) => changes.extend(c.into_iter().map(|(k, v)| (k, Some(v)))),
                    Err(e) => return refuse(&a, e),
                }
            }
            if let Err(e) = idle::change(paths, &changes) {
                return refuse(&a, e);
            }
            finish(paths, &a)
        }
        Some(IdleCmd::Preset { name }) => {
            let Some(changes) = idle::preset_changes(name) else {
                let names: Vec<&str> = idle::PRESETS.iter().map(|(n, _)| *n).collect();
                return refuse(
                    &a,
                    format!("unknown preset {name:?} ({})", names.join(", ")),
                );
            };
            if let Err(e) = idle::change(paths, &changes) {
                return refuse(&a, e);
            }
            finish(paths, &a)
        }
        Some(IdleCmd::Undo) => {
            if let Err(e) = idle::undo(paths) {
                return refuse(&a, e);
            }
            finish(paths, &a)
        }
        Some(IdleCmd::Apply) => finish(paths, &a),
        Some(IdleCmd::Off) => {
            idle::awake_off(paths);
            awake_doc(paths, &a)
        }
        Some(IdleCmd::StayAwake { duration, time }) => {
            let d = duration.trim().to_ascii_lowercase();
            let r = match d.as_str() {
                "off" | "stop" | "end" => {
                    idle::awake_off(paths);
                    Ok(())
                }
                "toggle" => {
                    if idle::awake(paths).on {
                        idle::awake_off(paths);
                        Ok(())
                    } else {
                        idle::parse_awake(time.as_deref().unwrap_or("1h"))
                            .and_then(|s| idle::awake_on(paths, s).map(|_| ()))
                    }
                }
                _ => idle::parse_awake(&d).and_then(|s| idle::awake_on(paths, s).map(|_| ())),
            };
            if let Err(e) = r {
                return refuse(&a, e);
            }
            awake_doc(paths, &a)
        }
        Some(IdleCmd::Hook) => match idle::hook(paths) {
            Ok(h) => {
                if a.json {
                    println!("{}", json!({"schema": SCHEMA, "hook": h}));
                } else {
                    println!("{} {}: {}", h.outcome, h.file.display(), h.detail);
                    if let Some(b) = &h.backup {
                        println!("the file as it was: {}", b.display());
                    }
                }
                Ok(0)
            }
            Err(e) => refuse(&a, e),
        },
        Some(IdleCmd::Render { defaults }) => {
            let p = if *defaults {
                idle::defaults(paths).0
            } else {
                idle::load(paths).policy
            };
            match idle::render(paths, &p) {
                Ok(t) => {
                    if a.json {
                        println!("{}", json!({"schema": SCHEMA, "policy": p, "text": t}));
                    } else {
                        print!("{t}");
                    }
                    Ok(0)
                }
                Err(e) => refuse(&a, e),
            }
        }
        Some(IdleCmd::Start { detach: true }) => match idle::start_detached(paths) {
            Ok(started) => {
                println!(
                    "hypridle: {}",
                    if started {
                        "started"
                    } else {
                        "already running"
                    }
                );
                Ok(0)
            }
            Err(e) => refuse(&a, e),
        },
        Some(IdleCmd::Start { detach: false }) => {
            let e = idle::exec_hypridle(paths);
            eprintln!("bromigos idle start: hypridle: {e}");
            Ok(127)
        }
    }
}
