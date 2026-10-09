//! `bromigos setup`'s terminal UI: one page per section (monitors, the AUR, hardware, theme, VECTOR's brain,
//! his voice, the homelab; the creation tools, a page per capability, then nolgia's
//! sign-in), then a review page. It only collects answers; the
//! caller applies them (bromigos_core::setup) once the terminal is back to normal, so the
//! steps that print (building the voice, signing in) show their own output.
//!
//! Keys: ↑/↓ choose, Tab moves into a choice's fields, typing edits them, Enter goes on,
//! Esc goes back (or skips the section from its first page), Ctrl-C leaves, changing nothing.

use std::io;

use std::collections::BTreeMap;

use bromigos_core::accessibility::Settings;
use bromigos_core::create::{self, CreateAnswer, Server};
use bromigos_core::setup::{
    AccessibilityAnswer, Answers, AurAnswer, HardwareAnswer, HomelabAnswer, Monitor,
    MonitorsAnswer, OLLAMA_URL, PeripheralsAnswer, TargetsAnswer, ThemeAnswer, VectorAnswer,
    VoiceAnswer, default_targets,
};
use ratatui::crossterm::event::{self, Event, KeyCode, KeyEventKind, KeyModifiers};
use ratatui::layout::{Constraint, Layout};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, List, ListItem, ListState, Paragraph, Wrap};
use ratatui::{DefaultTerminal, Frame};

/// A text field belonging to a choice.
#[derive(Clone)]
pub struct Field {
    pub key: &'static str,
    pub label: &'static str,
    pub value: String,
}

#[derive(Clone)]
pub struct Choice {
    pub label: String,
    pub value: String,
    pub fields: Vec<Field>,
}

#[derive(Clone)]
pub struct Page {
    pub section: &'static str,
    /// Which part of the section (a capability on create's pages; "" otherwise).
    pub item: String,
    pub title: &'static str,
    pub help: String,
    pub choices: Vec<Choice>,
    pub sel: usize,
    /// None: the list has focus; Some(i): the selected choice's field i.
    pub focus: Option<usize>,
}

impl Page {
    fn chosen(&self) -> &Choice {
        &self.choices[self.sel]
    }
    fn field(&self, key: &str) -> Option<String> {
        self.chosen()
            .fields
            .iter()
            .find(|f| f.key == key)
            .map(|f| f.value.trim().to_string())
            .filter(|v| !v.is_empty())
    }
}

fn choice(label: impl Into<String>, value: &str) -> Choice {
    Choice {
        label: label.into(),
        value: value.into(),
        fields: vec![],
    }
}

/// What the pages need to know about this machine.
pub struct Context {
    pub monitors: Vec<Monitor>,
    /// What the AUR is and what's here, as the page's text (crate::aur::page_text).
    pub aur: String,
    /// The AUR is on now.
    pub aur_on: bool,
    /// What `bromigos hw` found and what its setup would do, as lines for the page.
    pub hardware: String,
    /// It has something to do.
    pub hardware_todo: bool,
    pub themes: Vec<String>,
    pub current_theme: String,
    /// The Wick's den variants installed (bromigOS's empty one, plus the user's own art).
    pub dens: Vec<String>,
    pub homelab_installed: bool,
    /// homelab.toml names AI services (a ComfyUI, a voice, a model server).
    pub homelab_ai: bool,
    pub nolgia_installed: bool,
    pub gpu: bool,
    /// The ComfyUI instances that answered (bromigos_core::create).
    pub servers: Vec<Server>,
    /// Peripheral modules whose device is connected.
    pub peripherals: Vec<PeripheralHere>,
    /// The accessibility settings now (bromigos_core::accessibility).
    pub accessibility: Settings,
}

/// A peripheral module whose device is here (bromigos_core::peripheral).
pub struct PeripheralHere {
    pub id: String,
    pub name: String,
    pub description: String,
    /// The devices found, by name.
    pub found: String,
    pub enabled: bool,
}

/// The pages for `sections` (all, or one), from what's known.
pub fn pages(cx: &Context, sections: &[&str]) -> Vec<Page> {
    let mut out = vec![];
    for s in sections {
        match *s {
            "monitors" => {
                let found = if cx.monitors.is_empty() {
                    "No connected outputs found.".to_string()
                } else {
                    cx.monitors
                        .iter()
                        .map(|m| {
                            let d = m.describe();
                            format!("  {}  {}  scale {}{}", m.output, m.mode(), m.scale, if d.is_empty() { String::new() } else { format!("  ({d})") })
                        })
                        .collect::<Vec<_>>()
                        .join("\n")
                };
                let primary = cx.monitors.iter().find(|m| m.focused).or(cx.monitors.first()).map(|m| m.output.clone()).unwrap_or_default();
                let order = cx.monitors.iter().map(|m| m.output.clone()).collect::<Vec<_>>().join(",");
                out.push(Page {
                    section: "monitors",
                    item: String::new(),
                    title: "Monitors",
                    help: format!(
                        "Found on this machine, left to right (scale: from each panel's pixel density):\n{found}\n\n\
                         The layout goes in your ~/.config/hypr/hyprland.lua (a marked block). Any monitor \
                         plugged in later lights up on its own. Tab to change the primary (where the live \
                         background and the panels go), the order, a scale or a refresh rate."
                    ),
                    choices: vec![
                        Choice {
                            label: "Use this layout".into(),
                            value: "auto".into(),
                            fields: vec![
                                Field { key: "primary", label: "primary output", value: primary },
                                Field { key: "order", label: "left to right (comma-separated)", value: order },
                                Field { key: "scale", label: "scales (OUTPUT=1.5, …; blank: from density)", value: String::new() },
                                Field { key: "refresh", label: "refresh rates (OUTPUT=144, …; blank: current)", value: String::new() },
                            ],
                        },
                        choice("Leave it: every output at its preferred mode", "skip"),
                    ],
                    sel: 0,
                    focus: None,
                });
            }
            "aur" => {
                out.push(Page {
                    section: "aur",
                    item: String::new(),
                    title: "The AUR",
                    help: cx.aur.clone(),
                    choices: vec![
                        choice("On: an AUR helper (bromigOS's paru), AUR packages in bromigos update", "on"),
                        choice("Off: leave the AUR out", "off"),
                    ],
                    sel: if cx.aur_on { 0 } else { 1 },
                    focus: None,
                });
            }
            "hardware" => {
                out.push(Page {
                    section: "hardware",
                    item: String::new(),
                    title: "Hardware",
                    help: format!(
                        "{}\n\nSetting it up installs what's missing and writes the system's part with sudo \
                         (an NVIDIA driver already installed is kept). `bromigos hw` shows it again, \
                         `bromigos hw setup` does it any time.",
                        cx.hardware
                    ),
                    choices: vec![
                        choice(
                            if cx.hardware_todo {
                                "Set it up now"
                            } else {
                                "Set it up (nothing to change)"
                            },
                            "auto",
                        ),
                        choice("Leave it", "skip"),
                    ],
                    sel: 0,
                    focus: None,
                });
            }
            "accessibility" => {
                let motion = [("full", "Full motion: everything moves as designed"),
                              ("reduced", "Reduced: calmer and slower; no parallax, flicker, flashes or static; windows fade"),
                              ("still", "Still: the live background holds a still frame; no window animations")];
                out.push(Page {
                    section: "accessibility",
                    item: "motion".into(),
                    title: "Motion",
                    help: "How much the desktop moves. The worlds keep their look either way; reduced takes \
                           out what can trouble the eyes or balance (parallax, flicker, lightning flashes, \
                           the unlock static), still holds the background as a picture that changes only \
                           when its readings do. bromigos accessibility motion … changes it any time."
                        .into(),
                    choices: motion.iter().map(|(v, l)| choice(*l, v)).collect(),
                    sel: motion.iter().position(|(v, _)| *v == cx.accessibility.motion).unwrap_or(0),
                    focus: None,
                });
                let contrast = [("normal", "Normal: the theme's own colours"),
                                ("high", "High: every colour raised to WCAG AAA (text 7:1), panels opaque")];
                out.push(Page {
                    section: "accessibility",
                    item: "contrast".into(),
                    title: "Contrast",
                    help: "High contrast renders the theme's colours (bar, menus, notifications, terminal, \
                           widgets, holograms) darker behind and brighter in front, keeping each colour's hue. \
                           bromigos accessibility contrast … changes it any time."
                        .into(),
                    choices: contrast.iter().map(|(v, l)| choice(*l, v)).collect(),
                    sel: contrast.iter().position(|(v, _)| *v == cx.accessibility.contrast).unwrap_or(0),
                    focus: None,
                });
            }
            "theme" => {
                let mut choices: Vec<Choice> = cx
                    .themes
                    .iter()
                    .map(|t| {
                        let mut c = choice(theme_label(t), t);
                        if t == "wick" && cx.dens.len() > 1 {
                            c.fields.push(Field { key: "den", label: "den variant", value: "empty".into() });
                        }
                        c
                    })
                    .collect();
                if choices.is_empty() {
                    choices.push(choice("wick", "wick"));
                }
                let sel = cx.themes.iter().position(|t| *t == cx.current_theme).unwrap_or(0);
                out.push(Page {
                    section: "theme",
                    item: String::new(),
                    title: "Theme",
                    help: "The whole desktop's look. The Wick is the phosphor console; the worlds are living \
                           scenes that read your machine. `bromigos theme set` switches any time."
                        .into(),
                    choices,
                    sel,
                    focus: None,
                });
            }
            "vector" => out.push(Page {
                section: "vector",
                item: String::new(),
                title: "VECTOR's brain",
                help: "VECTOR talks to an OpenAI-compatible model server. A local Ollama keeps it all on this \
                       machine (pacman -S ollama; ollama pull a model). Any other server works too: your homelab's \
                       LiteLLM, vLLM, a hosted API. The key stays in a file you point at."
                    .into(),
                choices: vec![
                    Choice {
                        label: format!("A local Ollama ({OLLAMA_URL})"),
                        value: "ollama".into(),
                        fields: vec![Field { key: "model", label: "model (blank: VECTOR's default)", value: String::new() }],
                    },
                    Choice {
                        label: "Another OpenAI-compatible server".into(),
                        value: "openai".into(),
                        fields: vec![
                            Field { key: "base_url", label: "base URL (…/v1)", value: String::new() },
                            Field { key: "api_key_file", label: "API key file (blank: none)", value: String::new() },
                            Field { key: "model", label: "model", value: String::new() },
                        ],
                    },
                    choice("Not now (VECTOR tries a local Ollama)", "none"),
                ],
                sel: 0,
                focus: None,
            }),
            "voice" => out.push(Page {
                section: "voice",
                item: String::new(),
                title: "VECTOR's voice",
                help: format!(
                    "The designed caretaker voice runs on a GPU ({}); Kokoro runs on the CPU. Either is built \
                     after this (minutes: it downloads its model).",
                    if cx.gpu { "this machine has one" } else { "none found here" }
                ),
                choices: vec![
                    choice("The designed voice (GPU)", "gpu"),
                    choice("Kokoro (CPU)", "cpu"),
                    choice("Off: text only (vector unmute later)", "off"),
                ],
                sel: if cx.gpu { 0 } else { 2 },
                focus: None,
            }),
            "homelab" => out.push(Page {
                section: "homelab",
                item: String::new(),
                title: "Homelab",
                help: if cx.homelab_installed {
                    "Point bromigOS at your homelab: a homelab.toml (docs/homelab.md) with your Prometheus, \
                     Argo, model servers and agents. Every integration stays off until its endpoint is set."
                        .into()
                } else {
                    "The homelab integrations are optional: sudo pacman -S bromigos-homelab, then \
                     bromigos setup homelab."
                        .into()
                },
                choices: if cx.homelab_installed {
                    vec![
                        Choice {
                            label: "Use a homelab.toml".into(),
                            value: "file".into(),
                            fields: vec![Field { key: "file", label: "path", value: String::new() }],
                        },
                        choice("Skip", "skip"),
                    ]
                } else {
                    vec![choice("Skip", "skip")]
                },
                // Skip: Enter goes on (the file's choice needs a path first)
                sel: if cx.homelab_installed { 1 } else { 0 },
                focus: None,
            }),
            "targets" => {
                let def = default_targets(cx.homelab_ai, cx.gpu, cx.nolgia_installed);
                let enc = |t: &TargetsAnswer| format!("{}|{}", t.order.join(","), t.cloud_for.join(","));
                let mut choices = vec![];
                if cx.homelab_ai {
                    choices.push(choice("Homelab first, then this machine; never the cloud", "homelab,local|"));
                    if cx.nolgia_installed {
                        choices.push(choice(
                            "Homelab first, then this machine; the cloud (credits) only for video loops neither can make",
                            "homelab,local|video.loop",
                        ));
                    }
                    choices.push(choice("Homelab, then this machine, then the cloud (credits) when neither can", "homelab,local,cloud|"));
                    choices.push(choice("This machine first, then the homelab", "local,homelab|"));
                }
                choices.push(choice("This machine only (never the cloud)", "local|"));
                if cx.nolgia_installed {
                    choices.push(choice("This machine, then the cloud (credits)", "local,cloud|"));
                    choices.push(choice("The cloud first (credits)", if cx.homelab_ai { "cloud,homelab,local|" } else { "cloud,local|" }));
                }
                let want = enc(&def);
                let sel = choices.iter().position(|c| c.value == want).unwrap_or(0);
                out.push(Page {
                    section: "targets",
                    item: String::new(),
                    title: "Where AI runs",
                    help: format!(
                        "Where bromigOS's AI work runs: the art tools (images, edits, cutouts, 3D, video loops),                          VECTOR's voice and his brain. Found: {}; {}; {}. Switch any time: bromigos target                          homelab|local|cloud.",
                        if cx.homelab_ai { "a homelab with AI services (homelab.toml)" } else { "no homelab AI services" },
                        if cx.gpu { "a GPU here" } else { "no GPU here" },
                        if cx.nolgia_installed { "nolgia (credits) installed" } else { "no nolgia" },
                    ),
                    choices,
                    sel,
                    focus: None,
                });
            }
            "create" => {
                let def = create::default_choice(&cx.servers, cx.nolgia_installed);
                let found = if cx.servers.is_empty() {
                    "No ComfyUI answered (this machine's 127.0.0.1:8188, a homelab.toml comfyui source, \
                     BROMIGOS_COMFYUI_URL)."
                        .to_string()
                } else {
                    cx.servers
                        .iter()
                        .map(|s| format!("ComfyUI {} at {}{}", s.name, s.url, s.gpu.as_deref().map(|g| format!(" ({g})")).unwrap_or_default()))
                        .collect::<Vec<_>>()
                        .join("; ")
                };
                for cap in create::CAPABILITIES {
                    let mut choices: Vec<Choice> = vec![choice(
                        "Follow where AI runs (bromigos target): the default",
                        "targets",
                    )];
                    let cloud = cx.nolgia_installed && !create::nolgia_model(cap).is_empty();
                    for sv in cx.servers.iter().filter(|sv| sv.caps.contains_key(*cap)) {
                        let wf = &sv.caps[*cap];
                        if cloud {
                            choices.push(choice(format!("ComfyUI {} ({wf}), then nolgia", sv.name), &format!("comfyui:{},nolgia", sv.name)));
                        }
                        choices.push(choice(format!("ComfyUI {} ({wf}) only: no credits", sv.name), &format!("comfyui:{}", sv.name)));
                    }
                    if cloud {
                        choices.push(choice("nolgia (hosted; credits)", "nolgia"));
                    }
                    choices.push(choice("None: off", "none"));
                    let want = def.providers.get(*cap).map(|v| v.join(",")).unwrap_or_else(|| "none".into());
                    let sel = choices.iter().position(|c| c.value == want).unwrap_or(0);
                    out.push(Page {
                        section: "create",
                        item: cap.to_string(),
                        title: "Creation",
                        help: format!("What makes {cap} for bromigOS's art tools (bromigos art make). Pin a choice \
                                       only to override where AI runs for this one.\n{found}"),
                        choices,
                        sel,
                        focus: None,
                    });
                }
                if cx.nolgia_installed {
                    out.push(Page {
                        section: "create",
                        item: "nolgia".into(),
                        title: "Creation",
                        help: "nolgia makes art on hosted models (credits). Sign in now, or later with nolgia auth login.".into(),
                        choices: vec![choice("Skip", "skip"), choice("Sign in now", "login")],
                        sel: 0,
                        focus: None,
                    });
                }
            }
            "peripherals" if !cx.peripherals.is_empty() => {
                let mut choices = vec![choice(
                    "Leave them as they are (bromigos peripheral, any time)",
                    "",
                )];
                for p in &cx.peripherals {
                    if p.enabled {
                        choices.push(choice(format!("Turn {} off", p.name), &format!("-{}", p.id)));
                    } else {
                        choices.push(choice(format!("Turn {} on", p.name), &p.id));
                    }
                }
                if cx.peripherals.iter().filter(|p| !p.enabled).count() > 1 {
                    let all: Vec<&str> = cx.peripherals.iter().filter(|p| !p.enabled).map(|p| p.id.as_str()).collect();
                    choices.push(choice("Turn them all on", &all.join(",")));
                }
                let found = cx
                    .peripherals
                    .iter()
                    .map(|p| format!("  {}{}: {} — {}", p.name, if p.enabled { " (on)" } else { "" }, p.found, p.description))
                    .collect::<Vec<_>>()
                    .join("\n");
                out.push(Page {
                    section: "peripherals",
                    item: String::new(),
                    title: "Peripherals",
                    help: format!(
                        "Optional modules for devices found here:\n{found}\n\n\
                         Turning one on installs what it needs (with sudo), binds its keys on that \
                         device only and starts its daemon (the dial, the lighting). Change its keys \
                         later in ~/.config/bromigos/peripherals.toml."
                    ),
                    choices,
                    sel: 0,
                    focus: None,
                });
            }
            _ => {}
        }
    }
    out
}

fn theme_label(t: &str) -> String {
    match t {
        "wick" => "wick: phosphor green on void, the Wick's console".into(),
        "mire" => "mire: a night bayou, the Sleepers, fireflies and rain".into(),
        "tidewell" => "tidewell: the sea at night, Greywater Light and the Choir".into(),
        other => other.into(),
    }
}

/// The answers the pages hold (skipped sections are left out).
pub fn answers(pages: &[Page], skipped: &[&str]) -> Answers {
    let mut a = Answers::default();
    for p in pages {
        if skipped.contains(&p.section) {
            continue;
        }
        let v = p.chosen().value.clone();
        match p.section {
            "monitors" => {
                let kv = |key: &str| -> BTreeMap<String, f64> {
                    p.field(key)
                        .unwrap_or_default()
                        .split(',')
                        .filter_map(|x| {
                            let (k, n) = x.split_once('=')?;
                            Some((k.trim().to_string(), n.trim().parse().ok()?))
                        })
                        .collect()
                };
                a.monitors = Some(MonitorsAnswer {
                    mode: v,
                    primary: p.field("primary"),
                    order: p
                        .field("order")
                        .map(|o| {
                            o.split(',')
                                .map(|x| x.trim().to_string())
                                .filter(|x| !x.is_empty())
                                .collect()
                        })
                        .unwrap_or_default(),
                    scale: kv("scale"),
                    refresh: kv("refresh"),
                })
            }
            "aur" => a.aur = Some(AurAnswer { mode: v }),
            "hardware" => a.hardware = Some(HardwareAnswer { mode: v }),
            "accessibility" => {
                let x = a
                    .accessibility
                    .get_or_insert_with(AccessibilityAnswer::default);
                if p.item == "motion" {
                    x.motion = Some(v);
                } else {
                    x.contrast = Some(v);
                }
            }
            "theme" => {
                a.theme = Some(ThemeAnswer {
                    name: v,
                    den: p.field("den"),
                })
            }
            "vector" => {
                a.vector = Some(VectorAnswer {
                    backend: v.clone(),
                    base_url: if v == "ollama" {
                        Some(OLLAMA_URL.into())
                    } else {
                        p.field("base_url")
                    },
                    api_key_file: p.field("api_key_file"),
                    model: p.field("model"),
                })
            }
            "voice" => a.voice = Some(VoiceAnswer { tier: v }),
            "homelab" => {
                a.homelab = Some(HomelabAnswer {
                    file: if v == "file" { p.field("file") } else { None },
                })
            }
            "targets" => {
                let (order, cloud) = v.split_once('|').unwrap_or((v.as_str(), ""));
                let list = |x: &str| {
                    x.split(',')
                        .map(str::trim)
                        .filter(|t| !t.is_empty())
                        .map(String::from)
                        .collect::<Vec<_>>()
                };
                a.targets = Some(TargetsAnswer {
                    order: list(order),
                    cloud_for: list(cloud),
                })
            }
            "peripherals" if !v.is_empty() => {
                let (off, on): (Vec<String>, Vec<String>) = v
                    .split(',')
                    .map(str::to_string)
                    .partition(|x| x.starts_with('-'));
                a.peripherals = Some(PeripheralsAnswer {
                    enable: on,
                    disable: off.into_iter().map(|x| x[1..].to_string()).collect(),
                    force: false,
                    system: true,
                })
            }
            "create" => {
                let c = a.create.get_or_insert_with(CreateAnswer::default);
                if p.item == "nolgia" {
                    c.nolgia_login = v == "login";
                } else {
                    c.providers
                        .insert(p.item.clone(), v.split(',').map(str::to_string).collect());
                }
            }
            _ => {}
        }
    }
    a
}

/// A summary line per answered section (the review page, and what the CLI prints).
pub fn summary(a: &Answers) -> Vec<String> {
    let mut out = vec![];
    if let Some(m) = &a.monitors {
        out.push(format!(
            "monitors  {}",
            if m.mode == "auto" {
                format!(
                    "{} (primary {})",
                    if m.order.is_empty() {
                        "as found".to_string()
                    } else {
                        m.order.join(", ")
                    },
                    m.primary.as_deref().unwrap_or("the focused")
                )
            } else {
                "left as is".to_string()
            }
        ));
    }
    if let Some(x) = &a.aur {
        out.push(format!(
            "aur       {}",
            if x.mode == "on" {
                "on (an AUR helper; AUR packages in bromigos update)"
            } else {
                "off (no AUR helper from bromigOS)"
            }
        ));
    }
    if let Some(h) = &a.hardware {
        out.push(format!(
            "hardware  {}",
            if h.mode == "auto" {
                "set up (bromigos hw setup)"
            } else {
                "left as is"
            }
        ));
    }
    if let Some(x) = &a.accessibility {
        out.push(format!(
            "access.   motion {}, contrast {}",
            x.motion.as_deref().unwrap_or("as is"),
            x.contrast.as_deref().unwrap_or("as is")
        ));
    }
    if let Some(t) = &a.theme {
        out.push(format!(
            "theme     {}{}",
            t.name,
            t.den
                .as_deref()
                .map(|d| format!(" (den: {d})"))
                .unwrap_or_default()
        ));
    }
    if let Some(v) = &a.vector {
        out.push(format!(
            "vector    {}{}{}",
            v.backend,
            v.base_url
                .as_deref()
                .map(|u| format!(" {u}"))
                .unwrap_or_default(),
            v.model
                .as_deref()
                .map(|m| format!(", model {m}"))
                .unwrap_or_default()
        ));
    }
    if let Some(v) = &a.voice {
        out.push(format!("voice     {}", v.tier));
    }
    if let Some(h) = &a.homelab {
        out.push(format!("homelab   {}", h.file.as_deref().unwrap_or("skip")));
    }
    if let Some(t) = &a.targets {
        out.push(format!(
            "targets   {}{}",
            t.order.join(" > "),
            if t.cloud_for.is_empty() {
                String::new()
            } else {
                format!(" (cloud also for {})", t.cloud_for.join(", "))
            }
        ));
    }
    if let Some(c) = &a.create {
        for (cap, p) in &c.providers {
            out.push(format!("create    {cap}: {}", p.join(" > ")));
        }
        if c.nolgia_login {
            out.push("create    nolgia: sign in".into());
        }
    }
    if let Some(p) = &a.peripherals {
        for id in &p.enable {
            out.push(format!("peripheral {id}: on"));
        }
        for id in &p.disable {
            out.push(format!("peripheral {id}: off"));
        }
    }
    out
}

/// Whether a page can go on (an OpenAI-compatible server needs its URL, a homelab file its path).
pub fn page_problem(p: &Page) -> Option<&'static str> {
    match (p.section, p.chosen().value.as_str()) {
        ("vector", "openai") if p.field("base_url").is_none() => {
            Some("give the server's base URL (Tab to the field)")
        }
        ("vector", "openai") if !p.field("base_url").is_some_and(|u| u.starts_with("http")) => {
            Some("the base URL starts with http:// or https://")
        }
        ("homelab", "file") if p.field("file").is_none() => {
            Some("give the homelab.toml's path, or choose Skip")
        }
        _ => None,
    }
}

/// Runs the pages; Some(answers) when the user confirmed, None when they left.
pub fn run(mut pages: Vec<Page>) -> io::Result<Option<Answers>> {
    let mut terminal = ratatui::init();
    let r = event_loop(&mut terminal, &mut pages);
    ratatui::restore();
    r
}

fn event_loop(t: &mut DefaultTerminal, pages: &mut [Page]) -> io::Result<Option<Answers>> {
    let mut at = 0usize; // pages.len() = the review page
    let mut skipped: Vec<&'static str> = vec![];
    let mut problem: Option<&'static str> = None;
    loop {
        t.draw(|f| draw(f, pages, at, &skipped, problem))?;
        let Event::Key(k) = event::read()? else {
            continue;
        };
        if k.kind != KeyEventKind::Press {
            continue;
        }
        problem = None;
        if k.code == KeyCode::Char('c') && k.modifiers.contains(KeyModifiers::CONTROL) {
            return Ok(None);
        }
        if at == pages.len() {
            match k.code {
                KeyCode::Enter => return Ok(Some(answers(pages, &skipped))),
                KeyCode::Esc | KeyCode::Left if !pages.is_empty() => at -= 1,
                KeyCode::Esc => return Ok(None),
                _ => {}
            }
            continue;
        }
        let p = &mut pages[at];
        match (p.focus, k.code) {
            (_, KeyCode::Tab) => {
                let n = p.chosen().fields.len();
                p.focus = match p.focus {
                    None if n > 0 => Some(0),
                    Some(i) if i + 1 < n => Some(i + 1),
                    _ => None,
                };
            }
            (_, KeyCode::BackTab) => {
                let n = p.chosen().fields.len();
                p.focus = match p.focus {
                    None if n > 0 => Some(n - 1),
                    Some(0) | None => None,
                    Some(i) => Some(i - 1),
                };
            }
            (None, KeyCode::Up) => p.sel = p.sel.saturating_sub(1),
            (None, KeyCode::Down) => p.sel = (p.sel + 1).min(p.choices.len() - 1),
            (Some(i), KeyCode::Char(c)) => {
                let s = p.sel;
                p.choices[s].fields[i].value.push(c);
            }
            (Some(i), KeyCode::Backspace) => {
                let s = p.sel;
                p.choices[s].fields[i].value.pop();
            }
            (_, KeyCode::Enter) => {
                if let Some(why) = page_problem(p) {
                    problem = Some(why);
                } else {
                    let sec = p.section;
                    skipped.retain(|s| *s != sec);
                    p.focus = None;
                    at += 1;
                }
            }
            (_, KeyCode::Esc) => {
                if p.focus.is_some() {
                    p.focus = None;
                } else if at == 0 {
                    return Ok(None);
                } else {
                    at -= 1;
                }
            }
            (None, KeyCode::Char('s')) => {
                // skip this section: leave its setting as it is
                let sec = p.section;
                if !skipped.contains(&sec) {
                    skipped.push(sec);
                }
                while at < pages.len() && pages[at].section == sec {
                    at += 1;
                }
            }
            _ => {}
        }
    }
}

const ACCENT: Color = Color::Rgb(57, 255, 20);
const DIM: Color = Color::Rgb(126, 146, 126);

fn draw(f: &mut Frame, pages: &[Page], at: usize, skipped: &[&str], problem: Option<&str>) {
    let area = f.area();
    let [head, body, foot] = Layout::vertical([
        Constraint::Length(3),
        Constraint::Min(5),
        Constraint::Length(2),
    ])
    .areas(area);
    let steps: Vec<Span> = pages
        .iter()
        .enumerate()
        .flat_map(|(i, p)| {
            let style = if i == at {
                Style::new().fg(ACCENT).add_modifier(Modifier::BOLD)
            } else if skipped.contains(&p.section) {
                Style::new().fg(DIM).add_modifier(Modifier::CROSSED_OUT)
            } else {
                Style::new().fg(DIM)
            };
            [Span::styled(p.title, style), Span::raw("  ")]
        })
        .chain([Span::styled(
            "Review",
            if at == pages.len() {
                Style::new().fg(ACCENT).add_modifier(Modifier::BOLD)
            } else {
                Style::new().fg(DIM)
            },
        )])
        .collect();
    f.render_widget(
        Paragraph::new(Line::from(steps)).block(
            Block::new()
                .borders(Borders::BOTTOM)
                .title(" bromigOS setup ")
                .title_style(Style::new().fg(ACCENT)),
        ),
        head,
    );
    let keys = if at == pages.len() {
        "Enter apply   Esc back   Ctrl-C leave (nothing changes)"
    } else {
        "↑/↓ choose   Tab fields   Enter next   s skip   Esc back   Ctrl-C leave"
    };
    let foot_line = match problem {
        Some(p) => Line::from(Span::styled(p, Style::new().fg(Color::Rgb(255, 118, 111)))),
        None => Line::from(Span::styled(keys, Style::new().fg(DIM))),
    };
    f.render_widget(Paragraph::new(foot_line), foot);

    if at == pages.len() {
        let a = answers(pages, skipped);
        let mut lines: Vec<Line> = vec![Line::from("This is what setup will do:"), Line::from("")];
        lines.extend(
            summary(&a)
                .into_iter()
                .map(|s| Line::from(Span::styled(s, Style::new().fg(ACCENT)))),
        );
        for s in skipped {
            lines.push(Line::from(Span::styled(
                format!("{s:<9} skipped (left as it is)"),
                Style::new().fg(DIM),
            )));
        }
        f.render_widget(Paragraph::new(lines).wrap(Wrap { trim: false }), body);
        return;
    }
    let p = &pages[at];
    let fields_h = p.chosen().fields.len() as u16 * 3;
    let [help, list, fields] = Layout::vertical([
        Constraint::Length(p.help.lines().count() as u16 + 2),
        Constraint::Length(p.choices.len() as u16 + 2),
        Constraint::Length(fields_h),
    ])
    .areas(body);
    f.render_widget(
        Paragraph::new(p.help.as_str())
            .wrap(Wrap { trim: false })
            .block(Block::new().title(format!(" {} ", p.title))),
        help,
    );
    let items: Vec<ListItem> = p
        .choices
        .iter()
        .map(|c| ListItem::new(c.label.as_str()))
        .collect();
    let mut st = ListState::default().with_selected(Some(p.sel));
    let hl = if p.focus.is_none() {
        Style::new().fg(Color::Black).bg(ACCENT)
    } else {
        Style::new().fg(ACCENT)
    };
    f.render_stateful_widget(
        List::new(items)
            .highlight_style(hl)
            .highlight_symbol("› ")
            .block(Block::bordered().border_style(Style::new().fg(DIM))),
        list,
        &mut st,
    );
    let rows =
        Layout::vertical(p.chosen().fields.iter().map(|_| Constraint::Length(3))).split(fields);
    for (i, fl) in p.chosen().fields.iter().enumerate() {
        let focused = p.focus == Some(i);
        let style = if focused {
            Style::new().fg(ACCENT)
        } else {
            Style::new().fg(DIM)
        };
        let text = if focused {
            format!("{}▏", fl.value)
        } else {
            fl.value.clone()
        };
        f.render_widget(
            Paragraph::new(text).block(
                Block::bordered()
                    .title(format!(" {} ", fl.label))
                    .border_style(style),
            ),
            rows[i],
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cx(homelab_installed: bool) -> Context {
        Context {
            monitors: vec![],
            aur: String::new(),
            aur_on: true,
            hardware: String::new(),
            hardware_todo: false,
            themes: vec!["wick".into()],
            current_theme: "wick".into(),
            dens: vec![],
            homelab_installed,
            homelab_ai: false,
            nolgia_installed: false,
            gpu: false,
            servers: vec![],
            peripherals: vec![],
            accessibility: Settings::default(),
        }
    }

    #[test]
    fn the_homelab_page_starts_on_skip() {
        for installed in [true, false] {
            let p = &pages(&cx(installed), &["homelab"])[0];
            assert_eq!(p.chosen().value, "skip", "installed: {installed}");
            // Enter on it goes on: nothing to fill in first
            assert!(p.chosen().fields.is_empty());
        }
    }
}
