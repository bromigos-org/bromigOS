//! VECTOR in Field Kit's terminal (docs/fieldkit-vector.md): `bromigos fieldkit` › VECTOR, on
//! a Field Kit medium and on bromigOS Server's console. Built to the operator's mock-up.
//!
//! Three columns where there's room (Wide): his presence on the left (the orb, the screen's one
//! FLARE; his state; his brain, BRODEC and whether the internet is used; what he's looking at,
//! which the person turns on and off and adds to), the conversation in the middle (fixes come
//! as a PLAN card), and on the right questions worth asking and his rules. Narrower screens
//! fold: Medium drops the right column (the questions become chips above the composer, the
//! rules go under `?`), Narrow is one column with a small orb beside his name, Tiny has no orb
//! and stacks the plan's buttons. It re-lays itself out on every frame, so a resize re-flows
//! it and the conversation keeps its place.
//!
//! His brain, what he sees and the actions he may take are the engine's (`fieldkit-engine
//! engine vector …`, fieldkit/lib/bromigos_fieldkit/vector_tools.py): this screen only talks
//! to it. Every action he proposes is shown with its exact change and runs only after the
//! person approves it here: Apply for a reversible one, typing a word for one that isn't (a
//! rollback, a command, a restart), a passphrase for mounting. While the emergency switch is on he
//! talks and reads, and the engine refuses to run anything.

pub mod orb;
pub mod pair;
// the Server section's entry point: crate::fieldkit_vector::pair(&look, engine)
#[allow(unused_imports)]
pub use pair::pair;

use std::cell::Cell;
use std::io;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::mpsc::{self, Receiver, Sender};
use std::thread;
use std::time::Duration;

use bromigos_tui::layout::{self, Breakpoint};
use bromigos_tui::widgets::{self, Tone, st};
use bromigos_tui::{Icon, Look};
use ratatui::Frame;
use ratatui::crossterm::event::{
    self, DisableMouseCapture, EnableMouseCapture, Event, KeyCode, KeyEventKind, KeyModifiers,
    MouseEventKind,
};
use ratatui::crossterm::execute;
use ratatui::layout::{Constraint, Layout, Margin, Rect};
use ratatui::style::{Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Clear, Paragraph};
use serde_json::{Value, json};

/// The left and right columns' widths on a Wide screen (the mock-up's).
const LEFT_W: u16 = 34;
const RIGHT_W: u16 = 38;

/// What the composer's `/` offers.
const COMMANDS: [(&str, &str); 8] = [
    ("/look", "what he's looking at"),
    ("/add PATH", "add a file or disk to it"),
    ("/fix", "Fix: he plans the fix"),
    ("/ask", "Ask: he explains"),
    ("/pair", "pair with BRODEC (your phone)"),
    ("/clear", "clear the conversation"),
    ("/rules", "his rules and the keys"),
    ("/help", "the same"),
];

/// His rules, as the engine keeps them (vector_tools.FIELDKIT_RULES and FORBIDDEN).
const RULES: [&str; 5] = [
    "asks before every change",
    "shows the exact edit first",
    "backs up, and can undo",
    "never money, never secrets",
    "never touches the emergency switch",
];

/// The tools whose changes Field Kit backs up (system.Backup), so Undo can put them back.
const BACKED_UP: [&str; 3] = ["fix", "grub_repair", "boot_options"];

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Who {
    Person,
    Vector,
    /// Field Kit itself: a refusal, a command's answer, the engine's own words.
    FieldKit,
}

#[derive(Debug, Clone)]
pub struct Msg {
    pub who: Who,
    pub text: String,
    /// What he read for this answer ("looked at: …").
    pub looked: Vec<String>,
    /// The plan that came with it (an index into `App::plans`).
    pub plan: Option<usize>,
}

impl Msg {
    fn new(who: Who, text: impl Into<String>) -> Msg {
        Msg {
            who,
            text: text.into(),
            looked: Vec::new(),
            plan: None,
        }
    }
}

/// An action he proposed, as the engine saved it.
#[derive(Debug, Clone, Default)]
pub struct Proposal {
    pub id: String,
    pub tool: String,
    pub title: String,
    pub change: String,
    /// A word to type to confirm ("rollback", "run", "reboot"); empty: Apply is enough.
    pub confirm: String,
    /// "passphrase" when the person must type one (mounting).
    pub needs: String,
}

impl Proposal {
    fn from(v: &Value) -> Proposal {
        let s = |k: &str| v[k].as_str().unwrap_or("").to_string();
        Proposal {
            id: s("id"),
            tool: s("tool"),
            title: s("title"),
            change: s("change"),
            confirm: s("confirm"),
            needs: s("needs"),
        }
    }

    /// Typed to approve: a word, or a passphrase.
    fn typed(&self) -> bool {
        !self.confirm.is_empty() || self.needs == "passphrase"
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StepState {
    Waiting,
    Running,
    Done,
    Failed,
    /// Not run: the person said not now, or a step before it stopped the plan.
    Skipped,
}

#[derive(Debug, Clone)]
pub struct Step {
    pub prop: Proposal,
    pub state: StepState,
    /// What Field Kit said when it ran.
    pub result: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PlanState {
    Open,
    Applying,
    Applied,
    /// Some steps ran, then one failed or the person stopped.
    Stopped,
    NotNow,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PlanKind {
    Fix,
    Undo,
    Restart,
}

/// A PLAN card: his proposals of one answer, in order, applied one after the other.
#[derive(Debug, Clone)]
pub struct Plan {
    pub kind: PlanKind,
    pub steps: Vec<Step>,
    pub state: PlanState,
    /// The exact changes shown (they are, until the person hides them).
    pub diff: bool,
    /// The selected button.
    pub button: usize,
}

/// A button on a plan card: its key and its words.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Button {
    Apply,
    Changes,
    NotNow,
    Restart,
    Undo,
}

impl Plan {
    fn new(kind: PlanKind, props: Vec<Proposal>) -> Plan {
        Plan {
            kind,
            steps: props
                .into_iter()
                .map(|prop| Step {
                    prop,
                    state: StepState::Waiting,
                    result: String::new(),
                })
                .collect(),
            state: PlanState::Open,
            diff: true,
            button: 0,
        }
    }

    /// How much could go wrong: a command, a power-off or an update is high; a rollback, the
    /// boot menu, the boot options or a restart medium; a fix (backed up) low.
    pub fn risk(&self) -> (&'static str, Tone) {
        let tools: Vec<&str> = self.steps.iter().map(|s| s.prop.tool.as_str()).collect();
        let words: Vec<&str> = self.steps.iter().map(|s| s.prop.confirm.as_str()).collect();
        if tools.contains(&"run_command")
            || words
                .iter()
                .any(|w| ["run", "poweroff", "update"].contains(w))
        {
            ("high", Tone::Bad)
        } else if tools
            .iter()
            .any(|t| ["rollback", "grub_repair", "boot_options"].contains(t))
            || words.contains(&"reboot")
        {
            ("medium", Tone::Warn)
        } else {
            ("low", Tone::Good)
        }
    }

    /// What's true about backups for these steps, in words (no promise Field Kit doesn't keep).
    pub fn backed(&self) -> String {
        let has = |names: &[&str]| {
            self.steps
                .iter()
                .any(|s| names.contains(&s.prop.tool.as_str()))
        };
        let mut out = Vec::new();
        if has(&BACKED_UP) {
            out.push("backed up first in Field Kit's backups (/var/lib/bromigos/fieldkit-backups) · Undo puts the files back");
        }
        if has(&["rollback"]) {
            out.push("a rollback keeps the system it replaces, beside it");
        }
        if has(&["undo"]) {
            out.push("puts files back from Field Kit's backups (they stay there)");
        }
        if has(&["run_command"]) {
            out.push("a command: nothing backs it up, and it can't be undone here");
        }
        if out.is_empty() {
            out.push("changes no files");
        }
        out.join(" · ")
    }

    /// Steps that left something Undo can work from.
    fn undoable(&self) -> Vec<String> {
        if self.kind != PlanKind::Fix {
            return Vec::new();
        }
        self.steps
            .iter()
            .rev()
            .filter(|s| {
                s.state == StepState::Done
                    && (BACKED_UP.contains(&s.prop.tool.as_str()) || s.prop.tool == "rollback")
            })
            .map(|s| s.prop.id.clone())
            .collect()
    }

    /// The buttons the card shows now.
    pub fn buttons(&self) -> Vec<Button> {
        match self.state {
            PlanState::Open => vec![Button::Apply, Button::Changes, Button::NotNow],
            PlanState::Applied | PlanState::Stopped => {
                let mut b = Vec::new();
                if self.state == PlanState::Applied && self.kind != PlanKind::Restart {
                    b.push(Button::Restart);
                }
                if !self.undoable().is_empty() {
                    b.push(Button::Undo);
                }
                b
            }
            _ => Vec::new(),
        }
    }
}

/// What he's looking at: one chip of "HE'S LOOKING AT".
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Ctx {
    /// last_boot, install, findings, or file:PATH
    pub key: String,
    pub label: String,
    pub on: bool,
}

/// What has the keys.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Focus {
    Composer,
    Plan,
    /// a chip of what he's looking at; the one past the end is "+ add a file or disk"
    Looking(usize),
    /// a suggested question
    Asking(usize),
}

/// Chatting, or typing the word (or passphrase) that approves a step.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Mode {
    Chat,
    Typing {
        plan: usize,
        step: usize,
        typed: String,
    },
}

/// A reply from the engine, from its thread.
enum Reply {
    Status(Value),
    Suggest(Value),
    Turn(Value),
    Ran(usize, usize, Value),
    Added(String, Value),
    Proposed(PlanKind, Vec<Value>),
    /// `vector pending`: the saved proposals, with their exact changes.
    Pending(Value),
    /// Done in the background; nothing to show.
    Quiet,
}

pub struct App {
    pub look: Look,
    engine: PathBuf,
    pub msgs: Vec<Msg>,
    pub plans: Vec<Plan>,
    pub input: String,
    pub status: Value,
    pub ctx: Vec<Ctx>,
    pub suggestions: Vec<String>,
    /// Fix mode: he plans the fix (Ask: he explains).
    pub fix: bool,
    pub focus: Focus,
    pub mode: Mode,
    pub busy: bool,
    /// His rules and the keys, as a sheet (`?`).
    pub help: bool,
    pub tick: u64,
    pub done: bool,
    /// The person asked to pair with BRODEC (Ctrl+P, /pair): `run` opens that screen.
    pub pairing: bool,
    /// Alt+X: a shell; `run` hands it the terminal and comes back to this screen as it was.
    pub shell: bool,
    /// `c` on a plan: its exact changes, as a sheet (the plan's index).
    pub commands: Option<usize>,
    /// What `y` copies (OSC 52), for `run` to send.
    pub copy: Option<String>,
    /// The conversation's scroll, in rows up from its end (0 follows the newest), so a
    /// resize keeps the place.
    pub back: usize,
    /// The conversation's height and length at the last draw, for PgUp/PgDn.
    page: Cell<(usize, usize)>,
    tx: Sender<Reply>,
    rx: Receiver<Reply>,
}

/// One engine call: `ENGINE engine vector ARGS…`, `stdin` given, its last JSON line read.
pub fn engine_call(engine: &Path, args: &[&str], stdin: Option<&str>) -> Value {
    let spawn = || {
        Command::new(engine)
            .arg("engine")
            .arg("vector")
            .args(args)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
    };
    // "text file busy": the engine is being written as it starts (an update in progress, or
    // another thread's fork holding it open for a moment); it goes in a moment
    let mut child = spawn();
    for _ in 0..50 {
        match &child {
            Err(e) if e.raw_os_error() == Some(26) => {
                thread::sleep(Duration::from_millis(20));
                child = spawn();
            }
            _ => break,
        }
    }
    let mut child = match child {
        Ok(c) => c,
        Err(e) => {
            return json!({"ok": false, "message": format!("Field Kit's engine isn't here ({e})")});
        }
    };
    if let Some(mut w) = child.stdin.take() {
        use std::io::Write;
        let _ = w.write_all(stdin.unwrap_or("").as_bytes());
    }
    let out = match child.wait_with_output() {
        Ok(o) => o,
        Err(e) => return json!({"ok": false, "message": e.to_string()}),
    };
    let text = String::from_utf8_lossy(&out.stdout);
    text.lines()
        .rev()
        .find_map(|l| serde_json::from_str::<Value>(l).ok())
        .unwrap_or_else(|| {
            json!({"ok": false, "message": "VECTOR isn't on this Field Kit yet (its engine has no vector verb)."})
        })
}

fn message(v: &Value) -> String {
    v["message"].as_str().unwrap_or("No answer.").to_string()
}

impl App {
    pub fn new(look: Look, engine: &Path) -> App {
        let (tx, rx) = mpsc::channel();
        App {
            look,
            engine: engine.to_path_buf(),
            msgs: vec![Msg::new(
                Who::FieldKit,
                "VECTOR answers here from his post. He sees what Field Kit sees (you choose what, on \
                 the left), and he proposes; nothing he proposes runs until you approve it here.",
            )],
            plans: Vec::new(),
            input: String::new(),
            status: json!({}),
            ctx: Vec::new(),
            suggestions: Vec::new(),
            fix: false,
            focus: Focus::Composer,
            mode: Mode::Chat,
            busy: false,
            help: false,
            tick: 0,
            done: false,
            pairing: false,
            shell: false,
            commands: None,
            copy: None,
            back: 0,
            page: Cell::new((10, 0)),
            tx,
            rx,
        }
    }

    fn spawn(&self, job: impl FnOnce(&Path) -> Reply + Send + 'static) {
        let (tx, engine) = (self.tx.clone(), self.engine.clone());
        thread::spawn(move || {
            let _ = tx.send(job(&engine));
        });
    }

    /// Asks the engine where his brain is and what's worth asking (in the background).
    pub fn refresh_status(&self) {
        self.spawn(|e| Reply::Status(engine_call(e, &["status"], None)));
        self.spawn(|e| Reply::Suggest(engine_call(e, &["suggest"], None)));
    }

    fn history(&self) -> Value {
        Value::Array(
            self.msgs
                .iter()
                .filter(|m| m.who != Who::FieldKit)
                .map(|m| {
                    json!({"role": if m.who == Who::Person { "user" } else { "assistant" }, "content": m.text})
                })
                .collect(),
        )
    }

    /// What the person lets him see, for the engine.
    pub fn context(&self) -> Value {
        let on = |k: &str| self.ctx.iter().any(|c| c.key == k && c.on);
        let files: Vec<&str> = self
            .ctx
            .iter()
            .filter(|c| c.on)
            .filter_map(|c| c.key.strip_prefix("file:"))
            .collect();
        json!({"last_boot": on("last_boot"), "install": on("install"), "findings": on("findings"), "files": files})
    }

    fn say(&mut self, text: impl Into<String>) {
        self.msgs.push(Msg::new(Who::FieldKit, text));
        self.back = 0;
    }

    /// What's typed: a command, or the person's turn.
    pub fn submit(&mut self) {
        let text = self.input.trim().to_string();
        if text.is_empty() || self.busy {
            return;
        }
        if text.starts_with('/') {
            self.input.clear();
            self.command(&text);
            return;
        }
        self.input.clear();
        self.msgs.push(Msg::new(Who::Person, text));
        self.back = 0;
        self.busy = true;
        let doc = json!({"messages": self.history(), "context": self.context(),
                         "mode": if self.fix { "fix" } else { "ask" }})
        .to_string();
        self.spawn(move |e| Reply::Turn(engine_call(e, &["ask"], Some(&doc))));
    }

    fn command(&mut self, text: &str) {
        let (cmd, arg) = text.split_once(' ').unwrap_or((text, ""));
        let arg = arg.trim().to_string();
        match cmd {
            "/look" => {
                let on: Vec<&str> = self
                    .ctx
                    .iter()
                    .filter(|c| c.on)
                    .map(|c| c.label.as_str())
                    .collect();
                self.say(if on.is_empty() {
                    "He's looking at nothing but this computer's basics. Turn things on under HE'S LOOKING AT (Tab), or /add a file or disk.".to_string()
                } else {
                    format!("He's looking at: {}. Only these go to his brain; Space turns one off.", on.join(", "))
                });
                self.focus = Focus::Looking(0);
            }
            "/add" if arg.is_empty() => {
                self.say("Say which: /add /etc/fstab, or /add /dev/nvme0n1 for a disk.")
            }
            "/add" => self.spawn(move |e| {
                let v = engine_call(e, &["add", &arg], None);
                Reply::Added(arg, v)
            }),
            "/fix" => self.fix = true,
            "/ask" => self.fix = false,
            "/pair" => self.pairing = true,
            "/clear" => {
                if self.plans.iter().any(|p| p.state == PlanState::Applying) {
                    self.say("A plan is still being applied; clear when it's done.");
                    return;
                }
                let open: Vec<usize> = (0..self.plans.len())
                    .filter(|i| self.plans[*i].state == PlanState::Open)
                    .collect();
                for i in open {
                    self.not_now(i);
                }
                self.msgs.truncate(1);
                self.plans.clear();
                self.focus = Focus::Composer;
                self.back = 0;
            }
            "/rules" | "/help" | "/?" => self.help = true,
            _ => self.say(format!(
                "There's no {cmd}. These work: {}.",
                COMMANDS.iter().map(|c| c.0).collect::<Vec<_>>().join(", ")
            )),
        }
    }

    /// Takes the engine's answers that arrived.
    pub fn pump(&mut self) {
        while let Ok(r) = self.rx.try_recv() {
            self.apply(r);
        }
    }

    fn apply(&mut self, r: Reply) {
        match r {
            Reply::Status(v) => {
                // the person's own toggles and added files stay
                let mut ctx: Vec<Ctx> = v["context"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .map(|c| {
                        let key = c["key"].as_str().unwrap_or("").to_string();
                        let on = self
                            .ctx
                            .iter()
                            .find(|o| o.key == key)
                            .map_or(c["on"].as_bool() == Some(true), |o| o.on);
                        Ctx {
                            label: c["label"].as_str().unwrap_or("").to_string(),
                            key,
                            on,
                        }
                    })
                    .filter(|c| !c.key.starts_with("file:"))
                    .collect();
                ctx.extend(
                    self.ctx
                        .iter()
                        .filter(|c| c.key.starts_with("file:"))
                        .cloned(),
                );
                self.ctx = ctx;
                self.status = v;
            }
            Reply::Suggest(v) => {
                self.suggestions = v["questions"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .filter_map(|q| q.as_str().map(String::from))
                    .collect();
            }
            Reply::Turn(v) => {
                self.busy = false;
                if v["ok"].as_bool() != Some(true) {
                    self.say(message(&v));
                    return;
                }
                if !v["brain"].is_null() || self.status["brain"].is_null() {
                    self.status["brain"] = v["brain"].clone();
                }
                self.status["switch_off"] = v["switch_off"].clone();
                let mut m = Msg::new(Who::Vector, v["reply"].as_str().unwrap_or("").trim());
                m.looked = v["looked_at"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .filter_map(|x| x.as_str().map(String::from))
                    .collect();
                let props: Vec<Proposal> = v["proposals"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .map(Proposal::from)
                    .collect();
                if !props.is_empty() {
                    m.plan = Some(self.add_plan(Plan::new(PlanKind::Fix, props)));
                }
                self.msgs.push(m);
                self.back = 0;
            }
            Reply::Ran(pi, si, v) => self.ran(pi, si, v),
            Reply::Quiet => {}
            Reply::Pending(v) => {
                // the engine's saved copy is the one that runs: show its words
                for item in v["pending"].as_array().into_iter().flatten() {
                    let id = item["id"].as_str().unwrap_or("");
                    let change = item["change"].as_str().unwrap_or("");
                    for p in &mut self.plans {
                        for st in &mut p.steps {
                            if st.prop.id == id && !change.is_empty() {
                                st.prop.change = change.to_string();
                            }
                        }
                    }
                }
            }
            Reply::Added(path, v) => {
                if v["ok"].as_bool() == Some(true) {
                    let key = format!("file:{path}");
                    if !self.ctx.iter().any(|c| c.key == key) {
                        self.ctx.push(Ctx {
                            key,
                            label: v["label"].as_str().unwrap_or(&path).to_string(),
                            on: true,
                        });
                    }
                    self.say(format!(
                        "He's looking at {path} too (at most its last 64 KB)."
                    ));
                } else {
                    self.say(message(&v));
                }
            }
            Reply::Proposed(kind, vals) => {
                let mut props = Vec::new();
                for v in vals {
                    if v["ok"].as_bool() == Some(true) {
                        props.push(Proposal::from(&v["proposal"]));
                    } else {
                        self.say(message(&v));
                    }
                }
                if props.is_empty() {
                    return;
                }
                let text = match kind {
                    PlanKind::Undo => {
                        "Undo: this puts back what the plan changed, from Field Kit's backups."
                    }
                    _ => "Restart: the computer starts again, so you can see the fix work.",
                };
                let pi = self.add_plan(Plan::new(kind, props));
                let mut m = Msg::new(Who::FieldKit, text);
                m.plan = Some(pi);
                self.msgs.push(m);
                self.back = 0;
                if kind == PlanKind::Restart {
                    self.apply_plan(pi);
                }
            }
        }
    }

    /// A new plan replaces one still waiting (declined), and takes the keys if nothing's typed.
    fn add_plan(&mut self, plan: Plan) -> usize {
        if let Some(i) = self.plans.iter().position(|p| p.state == PlanState::Open) {
            self.not_now(i);
        }
        self.plans.push(plan);
        if self.input.is_empty() {
            self.focus = Focus::Plan;
        }
        self.plans.len() - 1
    }

    /// The plan the card keys work on: the newest.
    pub fn active(&self) -> Option<usize> {
        self.plans.len().checked_sub(1)
    }

    fn decline(&self, ids: Vec<String>) {
        if ids.is_empty() {
            return;
        }
        self.spawn(move |e| {
            for id in &ids {
                engine_call(e, &["decide", id, "deny", "--by", "local"], None);
            }
            Reply::Quiet
        });
    }

    fn skip_rest(&mut self, pi: usize) -> Vec<String> {
        let mut ids = Vec::new();
        for s in &mut self.plans[pi].steps {
            if s.state == StepState::Waiting {
                s.state = StepState::Skipped;
                ids.push(s.prop.id.clone());
            }
        }
        ids
    }

    /// Not now: nothing runs; the engine hears it was declined.
    pub fn not_now(&mut self, pi: usize) {
        let ids = self.skip_rest(pi);
        self.plans[pi].state = PlanState::NotNow;
        self.decline(ids);
    }

    /// Apply: each step in order, through the same approval as ever (a typed word for one
    /// that can't be undone).
    pub fn apply_plan(&mut self, pi: usize) {
        if self.plans[pi].state != PlanState::Open {
            return;
        }
        self.plans[pi].state = PlanState::Applying;
        self.next_step(pi);
    }

    fn next_step(&mut self, pi: usize) {
        let Some(si) = self.plans[pi]
            .steps
            .iter()
            .position(|s| s.state == StepState::Waiting)
        else {
            let all = self.plans[pi]
                .steps
                .iter()
                .all(|s| s.state == StepState::Done);
            self.plans[pi].state = if all {
                PlanState::Applied
            } else {
                PlanState::Stopped
            };
            self.plans[pi].button = 0;
            return;
        };
        if self.plans[pi].steps[si].prop.typed() {
            self.mode = Mode::Typing {
                plan: pi,
                step: si,
                typed: String::new(),
            };
        } else {
            self.run_step(pi, si, None);
        }
    }

    fn run_step(&mut self, pi: usize, si: usize, passphrase: Option<String>) {
        self.mode = Mode::Chat;
        self.plans[pi].steps[si].state = StepState::Running;
        let id = self.plans[pi].steps[si].prop.id.clone();
        self.spawn(move |e| {
            Reply::Ran(
                pi,
                si,
                engine_call(e, &["run", &id, "--by", "local"], passphrase.as_deref()),
            )
        });
    }

    fn ran(&mut self, pi: usize, si: usize, v: Value) {
        let Some(step) = self.plans.get_mut(pi).and_then(|p| p.steps.get_mut(si)) else {
            return;
        };
        step.result = message(&v);
        if v["ok"].as_bool() == Some(true) {
            step.state = StepState::Done;
            self.next_step(pi);
        } else {
            step.state = StepState::Failed;
            let title = step.prop.title.clone();
            let ids = self.skip_rest(pi);
            self.plans[pi].state = PlanState::Stopped;
            self.decline(ids);
            self.say(format!(
                "It didn't work: {title}: {}. The steps after it didn't run.",
                message(&v)
            ));
        }
    }

    /// The person stopped at a step's typed approval: it and the rest don't run.
    fn stop_at(&mut self, pi: usize) {
        self.mode = Mode::Chat;
        let ids = self.skip_rest(pi);
        let any = self.plans[pi]
            .steps
            .iter()
            .any(|s| s.state == StepState::Done);
        self.plans[pi].state = if any {
            PlanState::Stopped
        } else {
            PlanState::NotNow
        };
        self.decline(ids);
    }

    fn press(&mut self, b: Button) {
        let Some(pi) = self.active() else { return };
        if !self.plans[pi].buttons().contains(&b) {
            return;
        }
        match b {
            Button::Apply => self.apply_plan(pi),
            Button::Changes => self.plans[pi].diff = !self.plans[pi].diff,
            Button::NotNow => self.not_now(pi),
            Button::Restart => self.spawn(|e| {
                Reply::Proposed(
                    PlanKind::Restart,
                    vec![engine_call(e, &["control", "reboot"], None)],
                )
            }),
            Button::Undo => {
                let ids = self.plans[pi].undoable();
                self.spawn(move |e| {
                    Reply::Proposed(
                        PlanKind::Undo,
                        ids.iter()
                            .map(|id| engine_call(e, &["undo", id], None))
                            .collect(),
                    )
                });
            }
        }
    }

    /// A plan's steps and their exact changes, as text (what `y` copies).
    pub fn plan_text(&self, pi: usize) -> String {
        let mut out = String::new();
        for (i, st) in self.plans[pi].steps.iter().enumerate() {
            out.push_str(&format!(
                "{}. {}\n{}\n\n",
                i + 1,
                st.prop.title,
                st.prop.change
            ));
        }
        out.trim_end().to_string()
    }

    fn focus_order(&self) -> Vec<Focus> {
        let mut v = vec![Focus::Composer];
        if self
            .active()
            .is_some_and(|pi| !self.plans[pi].buttons().is_empty())
        {
            v.push(Focus::Plan);
        }
        v.push(Focus::Looking(0));
        if !self.suggestions.is_empty() {
            v.push(Focus::Asking(0));
        }
        v
    }

    fn same(a: Focus, b: Focus) -> bool {
        std::mem::discriminant(&a) == std::mem::discriminant(&b)
    }

    /// One key.
    pub fn key(&mut self, code: KeyCode, mods: KeyModifiers) {
        if mods.contains(KeyModifiers::ALT) {
            // Alt+X: a shell from anywhere, as in the rest of Field Kit; other Alt keys are
            // Field Kit's section keys, which aren't typed here
            if matches!(code, KeyCode::Char('x') | KeyCode::Char('X')) {
                self.shell = true;
            }
            return;
        }
        if let Some(pi) = self.commands {
            match code {
                KeyCode::Esc | KeyCode::Char('c') | KeyCode::Char('q') | KeyCode::Enter => {
                    self.commands = None
                }
                KeyCode::Char('y') => self.copy = Some(self.plan_text(pi)),
                _ => {}
            }
            return;
        }
        if self.help {
            if matches!(
                code,
                KeyCode::Esc | KeyCode::Enter | KeyCode::Char('?') | KeyCode::Char('q')
            ) {
                self.help = false;
            }
            return;
        }
        if let Mode::Typing { plan, step, typed } = self.mode.clone() {
            let p = self.plans[plan].steps[step].prop.clone();
            let mut t = typed;
            match code {
                KeyCode::Esc => return self.stop_at(plan),
                KeyCode::Enter => {
                    if p.needs == "passphrase" && !t.is_empty() {
                        self.run_step(plan, step, Some(t));
                    } else if !p.confirm.is_empty() && widgets::typed_ok(&p.confirm, &t) {
                        self.run_step(plan, step, None);
                    }
                    return;
                }
                KeyCode::Backspace => {
                    t.pop();
                }
                KeyCode::Char(c) => t.push(c),
                _ => {}
            }
            self.mode = Mode::Typing {
                plan,
                step,
                typed: t,
            };
            return;
        }
        if mods.contains(KeyModifiers::CONTROL) {
            match code {
                KeyCode::Char('c') => self.done = true,
                KeyCode::Char('p') => self.pairing = true,
                _ => {}
            }
            return;
        }
        let (page, total) = self.page.get();
        match code {
            KeyCode::PageUp => {
                self.back = (self.back + page.max(1)).min(total.saturating_sub(page));
                return;
            }
            KeyCode::PageDown => {
                self.back = self.back.saturating_sub(page.max(1));
                return;
            }
            KeyCode::Tab => {
                let order = self.focus_order();
                let at = order
                    .iter()
                    .position(|f| Self::same(*f, self.focus))
                    .unwrap_or(0);
                self.focus = order[(at + 1) % order.len()];
                return;
            }
            KeyCode::BackTab => {
                self.fix = !self.fix;
                return;
            }
            _ => {}
        }
        match self.focus {
            Focus::Composer => match code {
                KeyCode::Esc if !self.input.is_empty() => self.input.clear(),
                KeyCode::Esc => self.done = true,
                KeyCode::Enter => self.submit(),
                KeyCode::Backspace => {
                    self.input.pop();
                }
                KeyCode::Char('?') if self.input.is_empty() => self.help = true,
                KeyCode::Char(c) => self.input.push(c),
                _ => {}
            },
            Focus::Plan => {
                let Some(pi) = self.active() else {
                    self.focus = Focus::Composer;
                    return;
                };
                let buttons = self.plans[pi].buttons();
                let sel = self.plans[pi].button.min(buttons.len().saturating_sub(1));
                match code {
                    KeyCode::Esc => self.focus = Focus::Composer,
                    KeyCode::Left | KeyCode::Up => self.plans[pi].button = sel.saturating_sub(1),
                    KeyCode::Right | KeyCode::Down => {
                        self.plans[pi].button = (sel + 1).min(buttons.len().saturating_sub(1))
                    }
                    KeyCode::Enter => {
                        if let Some(b) = buttons.get(sel) {
                            self.press(*b)
                        }
                    }
                    KeyCode::Char('a') => self.press(Button::Apply),
                    KeyCode::Char('d') => self.press(Button::Changes),
                    KeyCode::Char('n') => self.press(Button::NotNow),
                    KeyCode::Char('r') => self.press(Button::Restart),
                    KeyCode::Char('u') => self.press(Button::Undo),
                    KeyCode::Char('c') => {
                        self.commands = Some(pi);
                        self.spawn(|e| Reply::Pending(engine_call(e, &["pending"], None)));
                    }
                    _ => {}
                }
                let idle = self.active().is_some_and(|pi| {
                    self.plans[pi].buttons().is_empty()
                        && self.plans[pi].state != PlanState::Applying
                });
                if idle && !matches!(self.mode, Mode::Typing { .. }) {
                    self.focus = Focus::Composer;
                }
            }
            Focus::Looking(i) => {
                let n = self.ctx.len() + 1;
                match code {
                    KeyCode::Esc => self.focus = Focus::Composer,
                    KeyCode::Up | KeyCode::Left => self.focus = Focus::Looking(i.saturating_sub(1)),
                    KeyCode::Down | KeyCode::Right => {
                        self.focus = Focus::Looking((i + 1).min(n - 1))
                    }
                    KeyCode::Char(' ') | KeyCode::Enter if i < self.ctx.len() => {
                        self.ctx[i].on = !self.ctx[i].on
                    }
                    KeyCode::Char(' ') | KeyCode::Enter => {
                        self.input = "/add ".into();
                        self.focus = Focus::Composer;
                    }
                    KeyCode::Delete | KeyCode::Char('x')
                        if i < self.ctx.len() && self.ctx[i].key.starts_with("file:") =>
                    {
                        self.ctx.remove(i);
                        self.focus = Focus::Looking(i.min(self.ctx.len()));
                    }
                    _ => {}
                }
            }
            Focus::Asking(i) => {
                let n = self.suggestions.len();
                match code {
                    KeyCode::Esc => self.focus = Focus::Composer,
                    KeyCode::Up | KeyCode::Left => self.focus = Focus::Asking(i.saturating_sub(1)),
                    KeyCode::Down | KeyCode::Right => {
                        self.focus = Focus::Asking((i + 1).min(n.saturating_sub(1)))
                    }
                    KeyCode::Enter if i < n => {
                        self.input = self.suggestions[i].clone();
                        self.focus = Focus::Composer;
                        self.submit();
                    }
                    _ => {}
                }
            }
        }
    }

    /// The mouse wheel scrolls the conversation.
    pub fn wheel(&mut self, down: bool) {
        let (page, total) = self.page.get();
        self.back = if down {
            self.back.saturating_sub(3)
        } else {
            (self.back + 3).min(total.saturating_sub(page))
        };
    }

    /// His state, in words, under his name.
    pub fn state(&self) -> (String, Tone) {
        if self.status["switch_off"].as_bool() == Some(true) {
            return ("emergency switch on · only talks".into(), Tone::Warn);
        }
        if self.busy {
            return ("thinking".into(), Tone::Good);
        }
        let last = self.active().map(|i| (&self.plans[i], self.plans[i].state));
        match last {
            _ if self.plans.iter().any(|p| p.state == PlanState::Applying)
                || matches!(self.mode, Mode::Typing { .. }) =>
            {
                if matches!(self.mode, Mode::Typing { .. }) {
                    ("waiting for you".into(), Tone::Warn)
                } else {
                    ("applying the plan".into(), Tone::Warn)
                }
            }
            Some((_, PlanState::Open)) => ("waiting for you".into(), Tone::Warn),
            Some((p, PlanState::Applied)) if p.kind != PlanKind::Restart => {
                ("done · restart to check it".into(), Tone::Good)
            }
            _ => ("here · ask anything".into(), Tone::Calm),
        }
    }

    /// His brain, short: "lab · node-a", or that there's none.
    pub fn brain(&self) -> (String, Tone) {
        let b = &self.status["brain"];
        if b.is_object() {
            let src = b["source"].as_str().unwrap_or("");
            let short = if src.starts_with("the lab bridge") {
                "lab bridge".to_string()
            } else if src.starts_with("the lab") {
                "lab".to_string()
            } else {
                src.split(" (")
                    .next()
                    .unwrap_or(src)
                    .trim_start_matches("the ")
                    .to_string()
            };
            let host = b["host"].as_str().unwrap_or("");
            (
                if host.is_empty() {
                    short
                } else {
                    format!("{short} · {host}")
                },
                Tone::Good,
            )
        } else if self.status.get("ok").is_some() {
            ("none · findings only".into(), Tone::Warn)
        } else {
            ("looking…".into(), Tone::Calm)
        }
    }

    fn paired(&self) -> bool {
        self.status["brodec"].as_str() == Some("paired")
    }

    /// The chips under his name: (icon, words, tone).
    fn chips(&self) -> Vec<(Icon, String, Tone)> {
        let (brain, bt) = self.brain();
        let brodec = match self.status["brodec"].as_str() {
            Some("paired") => ("BRODEC: paired".to_string(), Tone::Good),
            Some("waiting") | Some("starting") => ("BRODEC: pairing".into(), Tone::Warn),
            _ => ("BRODEC: not paired".into(), Tone::Calm),
        };
        let net = match self.status["no_internet"].as_bool() {
            Some(true) => ("no internet used".to_string(), Tone::Good),
            Some(false) => ("uses the internet".into(), Tone::Warn),
            None => ("…".into(), Tone::Calm),
        };
        vec![
            (Icon::Chip, format!("brain: {brain}"), bt),
            (Icon::Remote, brodec.0, brodec.1),
            (
                if net.1 == Tone::Warn {
                    Icon::Network
                } else {
                    Icon::NoNetwork
                },
                net.0,
                net.1,
            ),
        ]
    }
}

// ------------------------------------------------------------------ drawing

fn tone(look: &Look, t: Tone) -> ratatui::style::Color {
    match t {
        Tone::Calm => look.pal.muted,
        Tone::Good => look.pal.primary,
        Tone::Warn => look.pal.warn,
        Tone::Bad => look.pal.danger,
    }
}

fn bold(c: ratatui::style::Color) -> Style {
    st(c).add_modifier(Modifier::BOLD)
}

fn ell(look: &Look) -> &'static str {
    if look.ascii { "..." } else { "…" }
}

fn dot(look: &Look) -> &'static str {
    if look.ascii { " - " } else { " · " }
}

/// A Glass panel with its title in capitals and its icon; returns the space inside.
fn boxed(f: &mut Frame, area: Rect, look: &Look, icon: Icon, title: &str, active: bool) -> Rect {
    let t = format!("{} {}", icon.of(look), title.to_uppercase());
    let t = layout::truncate(&t, area.width.saturating_sub(4) as usize, look.ascii);
    let block = widgets::glass(look, &t, active);
    let inner = block.inner(area).inner(Margin::new(1, 0));
    f.render_widget(block, area);
    inner
}

/// The whole screen.
pub fn draw(f: &mut Frame, app: &App) {
    let look = &app.look;
    let area = f.area();
    if layout::too_small(area) {
        layout::too_small_screen(f, area, look);
        return;
    }
    f.render_widget(
        Paragraph::new("").style(Style::new().bg(look.pal.void)),
        area,
    );
    let [top, body, bottom] = Layout::vertical([
        Constraint::Length(2),
        Constraint::Min(4),
        Constraint::Length(2),
    ])
    .areas(area);
    top_bar(f, top, app);
    bottom_bar(f, bottom, app);
    let bp = Breakpoint::of(area.width);
    let centre = match bp {
        Breakpoint::Wide => {
            let [left, _, centre, _, right] = Layout::horizontal([
                Constraint::Length(LEFT_W),
                Constraint::Length(1),
                Constraint::Min(40),
                Constraint::Length(1),
                Constraint::Length(RIGHT_W),
            ])
            .areas(body);
            draw_presence(f, left, app);
            draw_side(f, right, app);
            centre
        }
        Breakpoint::Medium => {
            let (left, centre) = layout::columns(body, LEFT_W, 1);
            draw_presence(f, left, app);
            centre
        }
        _ => {
            let h = if bp == Breakpoint::Narrow { 5 } else { 3 };
            let (strip, rest) = layout::stack(body, h, 0);
            draw_strip(f, strip, app, bp);
            rest
        }
    };
    draw_conversation(f, centre, app, bp);
    if let Mode::Typing { plan, step, typed } = &app.mode {
        draw_typed(f, centre, app, *plan, *step, typed);
    }
    if app.help {
        draw_help(f, body, app);
    }
    if let Some(pi) = app.commands {
        draw_commands_sheet(f, body, app, pi);
    }
    if look.ascii {
        ascii_only(f);
    }
}

/// The ASCII look: what came from elsewhere (his words, the engine's labels) in plain
/// characters too, so a console without those glyphs shows no boxes.
fn ascii_only(f: &mut Frame) {
    let buf = f.buffer_mut();
    let area = buf.area;
    for y in area.top()..area.bottom() {
        for x in area.left()..area.right() {
            let cell = &mut buf[(x, y)];
            if cell.symbol().is_ascii() {
                continue;
            }
            let plain = match cell.symbol() {
                "·" | "—" | "–" | "‐" => "-",
                "›" | "→" => ">",
                "‹" | "←" => "<",
                "…" => ".",
                "‘" | "’" => "'",
                "“" | "”" => "\"",
                "●" | "•" => "*",
                "×" => "x",
                "°" => "o",
                _ => "?",
            };
            cell.set_symbol(plain);
        }
    }
}

fn top_bar(f: &mut Frame, area: Rect, app: &App) {
    let look = &app.look;
    let p = &look.pal;
    let [row, rule] = Layout::vertical([Constraint::Length(1), Constraint::Length(1)]).areas(area);
    let mark = if look.ascii { "/" } else { "◢" };
    let crumb = if look.ascii {
        "Home > VECTOR"
    } else {
        "Home › VECTOR"
    };
    // the engine's switch_off: one of the switch's markers is there (vector repo, switch.py),
    // so the emergency switch is ON and he only talks
    let off = app.status["switch_off"].as_bool() == Some(true);
    let switch = (
        Icon::Shield,
        if off {
            "EMERGENCY SWITCH ON · he only talks".to_string()
        } else {
            "emergency switch: off · he can act".to_string()
        },
        if off { Tone::Warn } else { Tone::Calm },
    );
    let tiny = Breakpoint::of(area.width) == Breakpoint::Tiny;
    let left = if tiny {
        format!(" {mark} VECTOR")
    } else {
        format!(" {mark} BROMIGOS // FIELD KIT   ")
    };
    let used = layout::display_width(&left) as u16
        + if tiny {
            0
        } else {
            layout::display_width(crumb) as u16
        }
        + 2;
    // the same chips as every Field Kit screen, then the switch; when the row is short the
    // last ones go first (the clock, the stick), the network and the switch stay longest
    let mut chips = crate::fieldkit::bar_chips(look, &app.status["bar"]);
    chips.push(switch);
    while chips.len() > 1
        && crate::fieldkit::chips_width(look, &chips) + 1 > area.width.saturating_sub(used)
    {
        chips.remove(chips.len() - 2);
    }
    let mut cs = crate::fieldkit::chip_spans(look, &chips);
    cs.push(Span::raw(" "));
    let cw = (crate::fieldkit::chips_width(look, &chips) + 1).min(area.width.saturating_sub(used));
    let [l, r] = Layout::horizontal([Constraint::Min(1), Constraint::Length(cw)]).areas(row);
    let mut spans = vec![Span::styled(left.clone(), bold(p.primary))];
    if !tiny {
        spans.push(Span::styled(crumb, st(p.muted)));
    }
    f.render_widget(Paragraph::new(Line::from(spans)), l);
    f.render_widget(Paragraph::new(Line::from(cs)), r);
    f.render_widget(
        Paragraph::new(Span::styled(
            (if look.ascii { "=" } else { "━" }).repeat(rule.width as usize),
            st(p.dim),
        )),
        rule,
    );
}

/// The keys for what has them, and the hint for it.
fn keys(app: &App) -> (Vec<(&'static str, &'static str)>, String) {
    if app.help {
        return (vec![("Esc", "close")], String::new());
    }
    if let Mode::Typing { .. } = app.mode {
        return (
            vec![("Enter", "go ahead"), ("Esc", "stop here")],
            "This step can't be undone simply: it asks for the word".into(),
        );
    }
    match app.focus {
        Focus::Composer => (
            vec![
                ("Enter", "ask"),
                ("Tab", "move"),
                ("Shift+Tab", "Ask/Fix"),
                ("PgUp", "scroll"),
                ("Esc", "back"),
            ],
            if app.fix {
                "Fix: he checks, explains, and plans the fix as steps you approve".into()
            } else {
                "Ask: he explains; Shift+Tab for Fix · / for commands".into()
            },
        ),
        Focus::Plan => {
            let p = app.active().map(|i| &app.plans[i]);
            match p.map(|p| p.state) {
                Some(PlanState::Open) => (
                    vec![
                        ("a", "apply"),
                        ("d", "changes"),
                        ("c", "commands"),
                        ("n", "not now"),
                        ("Tab", "move"),
                    ],
                    "Enter or a applies the plan; d shows or hides the exact changes".into(),
                ),
                _ => (
                    vec![("r", "restart"), ("u", "undo"), ("Tab", "move")],
                    "Undo puts the changed files back from Field Kit's backups".into(),
                ),
            }
        }
        Focus::Looking(_) => (
            vec![
                ("Space", "on/off"),
                ("↑↓", "move"),
                ("x", "remove"),
                ("Tab", "move"),
            ],
            "Only what's on goes to his brain".into(),
        ),
        Focus::Asking(_) => (
            vec![("Enter", "ask this"), ("↑↓", "move"), ("Tab", "move")],
            "From what Field Kit found on this computer".into(),
        ),
    }
}

fn bottom_bar(f: &mut Frame, area: Rect, app: &App) {
    let look = &app.look;
    let p = &look.pal;
    let [rule, row] = Layout::vertical([Constraint::Length(1), Constraint::Length(1)]).areas(area);
    f.render_widget(
        Paragraph::new(Span::styled(
            (if look.ascii { "-" } else { "─" }).repeat(rule.width as usize),
            st(p.dim),
        )),
        rule,
    );
    let (keys, hint) = keys(app);
    let mut spans = vec![Span::raw(" ")];
    let mut used = 1;
    for (k, what) in keys {
        let k = if look.ascii {
            k.replace("↑↓", "arrows")
        } else {
            k.to_string()
        };
        let w = layout::display_width(&k) + what.len() + 3;
        if used + w > row.width as usize {
            break;
        }
        used += w;
        spans.push(Span::styled(k, st(p.soft)));
        spans.push(Span::styled(format!(" {what}  "), st(p.muted)));
    }
    let room = (row.width as usize).saturating_sub(used + 1);
    let tip = if hint.is_empty() || room < 12 {
        String::new()
    } else {
        layout::truncate(
            &format!("{} {hint} ", Icon::Info.of(look)),
            room,
            look.ascii,
        )
    };
    let tw = layout::display_width(&tip) as u16;
    let [l, r] = Layout::horizontal([Constraint::Min(1), Constraint::Length(tw)]).areas(row);
    f.render_widget(Paragraph::new(Line::from(spans)), l);
    f.render_widget(Paragraph::new(Span::styled(tip, st(p.accent))), r);
}

/// A chip: its icon and words on the panel's surface (icons only when `icons_only`).
fn chip(look: &Look, icon: Icon, text: &str, t: Tone, width: usize) -> Line<'static> {
    let words = layout::truncate(&format!(" {} {text} ", icon.of(look)), width, look.ascii);
    Line::from(Span::styled(
        words,
        Style::new().bg(look.pal.panel).fg(if t == Tone::Calm {
            look.pal.soft
        } else {
            tone(look, t)
        }),
    ))
}

fn centred(line: Line<'static>, width: u16) -> Line<'static> {
    let pad = (width as usize).saturating_sub(line.width()) / 2;
    let mut spans = vec![Span::raw(" ".repeat(pad))];
    spans.extend(line.spans);
    Line::from(spans)
}

fn name_line(look: &Look) -> Line<'static> {
    Line::from(Span::styled("V E C T O R", bold(look.pal.primary)))
}

fn state_line(app: &App) -> Line<'static> {
    let look = &app.look;
    let (words, t) = app.state();
    let dot = if look.ascii { "*" } else { "●" };
    Line::from(vec![
        Span::styled(format!("{dot} "), st(tone(look, t))),
        Span::styled(
            words,
            st(if t == Tone::Calm {
                look.pal.soft
            } else {
                tone(look, t)
            }),
        ),
    ])
}

/// Left column (Wide, Medium): the orb, his name and state, the chips, what he's looking at.
fn draw_presence(f: &mut Frame, area: Rect, app: &App) {
    let look = &app.look;
    let looking_h = (app.ctx.len() as u16 + 3).min(10);
    let fixed = 1 + 1 + 1 + 1 + 3 + 1 + looking_h;
    let braille = look.mode == bromigos_tui::Mode::Truecolor && !look.ascii;
    let t = if look.motion {
        app.tick as f64 * 0.12
    } else {
        0.0
    };
    let sizes: &[(usize, usize)] = if braille {
        &[(22, 11), (16, 8), (10, 5)]
    } else {
        &[orb::PLAIN]
    };
    let size = sizes
        .iter()
        .copied()
        .find(|s| fixed + s.1 as u16 <= area.height && s.0 as u16 <= area.width)
        .unwrap_or((0, 0));
    let mut lines: Vec<Line> = Vec::new();
    if size.1 > 0 {
        lines.push(Line::from(""));
        for l in orb::lines(look, t, size) {
            lines.push(centred(l, area.width));
        }
    }
    lines.push(Line::from(""));
    lines.push(centred(name_line(look), area.width));
    lines.push(centred(state_line(app), area.width));
    lines.push(Line::from(""));
    for (icon, text, t) in app.chips() {
        let mut l = chip(look, icon, &text, t, area.width.saturating_sub(1) as usize);
        l.spans.insert(0, Span::raw(" "));
        lines.push(l);
    }
    let top_h = (lines.len() as u16).min(area.height);
    let (top, rest) = layout::stack(area, top_h, 1);
    f.render_widget(Paragraph::new(lines), top);
    if rest.height >= 3 {
        let r = Rect {
            height: looking_h.min(rest.height),
            ..rest
        };
        draw_looking(f, r, app);
    }
}

fn ctx_icon(c: &Ctx) -> Icon {
    match c.key.as_str() {
        "last_boot" => Icon::List,
        "install" => Icon::Disk,
        "findings" => Icon::Repair,
        k if k.starts_with("file:/dev/") => Icon::Disk,
        _ => Icon::Folder,
    }
}

/// A context chip: on (lit), off (faint), focused (marked).
fn ctx_span(look: &Look, c: Option<&Ctx>, focused: bool, short: bool) -> Span<'static> {
    let p = &look.pal;
    let Some(c) = c else {
        let t = if short {
            "+ add"
        } else {
            "+ add a file or disk"
        };
        return Span::styled(
            format!("[ {t} ]"),
            if focused {
                Style::new().bg(p.selection).fg(p.primary)
            } else {
                st(p.muted)
            },
        );
    };
    let label = if short {
        layout::truncate(&c.label, 18, look.ascii)
    } else {
        c.label.clone()
    };
    let text = if look.ascii {
        format!("[{}] {label}", if c.on { "x" } else { " " })
    } else if c.on {
        format!(" {} {label} ", ctx_icon(c).of(look))
    } else {
        format!(" ○ {label} ")
    };
    let mut s = if c.on {
        Style::new().bg(p.selection).fg(p.soft)
    } else {
        st(p.faint)
    };
    if focused {
        s = s
            .fg(p.white)
            .add_modifier(Modifier::BOLD | Modifier::UNDERLINED);
    }
    Span::styled(text, s)
}

fn draw_looking(f: &mut Frame, area: Rect, app: &App) {
    let look = &app.look;
    let focused = matches!(app.focus, Focus::Looking(_));
    let inner = boxed(f, area, look, Icon::Search, "He's looking at", focused);
    let sel = match app.focus {
        Focus::Looking(i) => Some(i),
        _ => None,
    };
    let mut lines: Vec<Line> = Vec::new();
    for i in 0..=app.ctx.len() {
        let mut s = ctx_span(look, app.ctx.get(i), sel == Some(i), false);
        s.content = layout::truncate(&s.content, inner.width as usize, look.ascii).into();
        lines.push(Line::from(s));
    }
    let off = sel
        .unwrap_or(0)
        .saturating_sub(inner.height.saturating_sub(1) as usize);
    layout::scroll_view(f, inner, look, lines, off);
}

/// Right column (Wide): questions worth asking, and his rules.
fn draw_side(f: &mut Frame, area: Rect, app: &App) {
    let look = &app.look;
    let p = &look.pal;
    let rules_h = (RULES.len() as u16 + 3).min(area.height / 2);
    let [ask, _, rules] = Layout::vertical([
        Constraint::Min(3),
        Constraint::Length(1),
        Constraint::Length(rules_h),
    ])
    .areas(area);
    let focused = matches!(app.focus, Focus::Asking(_));
    let inner = boxed(f, ask, look, Icon::Suggest, "Try asking", focused);
    let mut lines: Vec<Line> = Vec::new();
    let mut at = 0;
    if app.suggestions.is_empty() {
        lines.extend(widgets::wrap_hanging(
            "Nothing Field Kit found needs a question. Ask him anything.",
            inner.width,
            "",
            "",
            st(p.muted),
        ));
    }
    for (i, q) in app.suggestions.iter().enumerate() {
        let sel = app.focus == Focus::Asking(i);
        if sel {
            at = lines.len();
        }
        let style = if sel {
            Style::new()
                .bg(p.selection)
                .fg(p.white)
                .add_modifier(Modifier::BOLD)
        } else {
            st(p.soft)
        };
        lines.extend(widgets::wrap_hanging(q, inner.width, "", "", style));
        lines.push(Line::from(""));
    }
    let mut scroll = layout::Scroll::default();
    scroll.keep_visible(at, 2, inner.height as usize);
    layout::scroll_view(f, inner, look, lines, scroll.offset);
    let inner = boxed(f, rules, look, Icon::Shield, "His rules", false);
    let mut lines: Vec<Line> = Vec::new();
    for r in RULES {
        lines.extend(widgets::wrap_hanging(r, inner.width, "", "", st(p.muted)));
    }
    f.render_widget(Paragraph::new(lines), inner);
}

/// Narrow and Tiny: his name, state and chips in a strip (Narrow: a small orb beside them),
/// and what he's looking at on one chip line.
fn draw_strip(f: &mut Frame, area: Rect, app: &App, bp: Breakpoint) {
    let look = &app.look;
    let p = &look.pal;
    let t = if look.motion {
        app.tick as f64 * 0.12
    } else {
        0.0
    };
    let braille = look.mode == bromigos_tui::Mode::Truecolor && !look.ascii;
    let (orb_area, text) = if bp == Breakpoint::Narrow {
        let w = if braille { 10 } else { orb::PLAIN.0 as u16 };
        let (o, t) = layout::columns(area, w + 1, 1);
        (Some(o), t)
    } else {
        (None, area)
    };
    if let Some(o) = orb_area {
        let lines = orb::lines(look, t, (10, 5));
        f.render_widget(Paragraph::new(lines), o.inner(Margin::new(1, 0)));
    }
    let w = text.width as usize;
    let mut lines: Vec<Line> = Vec::new();
    let mut first = name_line(look);
    first.spans.push(Span::raw("  "));
    first.spans.extend(state_line(app).spans);
    lines.push(first);
    // the chips: words where they fit, icons alone on a Tiny screen
    let mut chips = Vec::new();
    for (icon, words, t) in app.chips() {
        let text = if bp == Breakpoint::Tiny {
            format!(" {} ", icon.of(look))
        } else {
            format!(" {} {words} ", icon.of(look))
        };
        chips.push(Span::styled(
            text,
            Style::new().bg(p.panel).fg(if t == Tone::Calm {
                p.soft
            } else {
                tone(look, t)
            }),
        ));
        chips.push(Span::raw(" "));
    }
    if bp == Breakpoint::Tiny {
        chips.push(Span::styled(
            layout::truncate(&app.brain().0, w.saturating_sub(14), look.ascii),
            st(p.muted),
        ));
    }
    lines.push(fit_row(chips, None, w, look));
    // what he's looking at, one line
    let sel = match app.focus {
        Focus::Looking(i) => Some(i),
        _ => None,
    };
    let mut spans = Vec::new();
    for i in 0..=app.ctx.len() {
        spans.push(ctx_span(look, app.ctx.get(i), sel == Some(i), true));
        spans.push(Span::raw(" "));
    }
    let label = Span::styled(
        if bp == Breakpoint::Tiny {
            "sees "
        } else {
            "looking at "
        },
        st(p.muted),
    );
    let row = fit_row(
        spans,
        sel.map(|i| i * 2),
        w.saturating_sub(label.width()),
        look,
    );
    let mut l = vec![label];
    l.extend(row.spans);
    lines.push(Line::from(l));
    f.render_widget(Paragraph::new(lines), text);
}

/// Spans on one row of `width`: the window that keeps span `keep` in view, cut with "…".
fn fit_row(
    spans: Vec<Span<'static>>,
    keep: Option<usize>,
    width: usize,
    look: &Look,
) -> Line<'static> {
    let widths: Vec<usize> = spans.iter().map(|s| s.width()).collect();
    let mut start = 0;
    if let Some(k) = keep {
        while start < k
            && widths[start..=k.min(widths.len() - 1)]
                .iter()
                .sum::<usize>()
                > width
        {
            start += 1;
        }
    }
    let mut out = Vec::new();
    let mut used = 0;
    if start > 0 {
        out.push(Span::styled(ell(look), st(look.pal.faint)));
        used += ell(look).len();
    }
    for s in spans.into_iter().skip(start) {
        let w = s.width();
        if used + w > width {
            let room = width.saturating_sub(used);
            if room > 2 {
                let style = s.style;
                out.push(Span::styled(
                    layout::truncate(&s.content, room, look.ascii),
                    style,
                ));
            }
            break;
        }
        used += w;
        out.push(s);
    }
    Line::from(out)
}

/// The conversation's lines, `w` wide.
fn conversation(app: &App, w: u16, bp: Breakpoint) -> Vec<Line<'static>> {
    let look = &app.look;
    let p = &look.pal;
    let (vedge, uedge) = if look.ascii {
        ("| ", " |")
    } else {
        ("▎ ", " ▕")
    };
    let mut lines: Vec<Line> = Vec::new();
    for (n, m) in app.msgs.iter().enumerate() {
        match m.who {
            Who::Person => {
                let max = ((w as usize) * 3 / 4)
                    .max(20)
                    .min(w as usize)
                    .saturating_sub(6);
                for (i, l) in layout::wrap(&m.text, max).into_iter().enumerate() {
                    let mut spans = Vec::new();
                    if i == 0 {
                        spans.push(Span::styled("You ", bold(p.accent)));
                    }
                    spans.push(Span::styled(l, st(p.soft)));
                    spans.push(Span::styled(uedge, st(p.accent)));
                    lines.push(Line::from(spans).right_aligned());
                }
            }
            Who::Vector => {
                let edge = |s: Vec<Span<'static>>| {
                    let mut v = vec![Span::styled(vedge, st(p.primary))];
                    v.extend(s);
                    Line::from(v)
                };
                lines.push(edge(vec![Span::styled("VECTOR", bold(p.primary))]));
                if !m.looked.is_empty() {
                    let text = format!(
                        "{} looked at: {}",
                        Icon::Search.of(look),
                        m.looked.join(dot(look))
                    );
                    for l in layout::wrap(&text, (w as usize).saturating_sub(2)) {
                        lines.push(edge(vec![Span::styled(l, st(p.faint))]));
                    }
                    lines.push(edge(vec![]));
                }
                for l in layout::wrap(&m.text, (w as usize).saturating_sub(2)) {
                    lines.push(edge(vec![Span::styled(l, st(p.text))]));
                }
            }
            Who::FieldKit => {
                let lead = if look.ascii { "- " } else { "· " };
                lines.extend(widgets::wrap_hanging(&m.text, w, lead, "  ", st(p.muted)));
            }
        }
        if let Some(pi) = m.plan {
            lines.push(Line::from(""));
            let indent = if bp >= Breakpoint::Narrow { 2 } else { 0 };
            let focused = app.focus == Focus::Plan && app.active() == Some(pi);
            for l in card(app, pi, w.saturating_sub(indent), focused, bp) {
                let mut v = vec![Span::raw(" ".repeat(indent as usize))];
                v.extend(l.spans);
                lines.push(Line::from(v));
            }
        }
        if n + 1 < app.msgs.len() || app.busy {
            lines.push(Line::from(""));
        }
    }
    if app.busy {
        let mut l = widgets::sweep(look, None, app.tick, w.saturating_sub(2).min(30));
        l.spans.insert(0, Span::styled(vedge, st(p.primary)));
        lines.push(l);
    }
    lines
}

/// A PLAN card, `w` wide with its frame.
fn card(app: &App, pi: usize, w: u16, focused: bool, bp: Breakpoint) -> Vec<Line<'static>> {
    let look = &app.look;
    let p = &look.pal;
    let plan = &app.plans[pi];
    let iw = (w as usize).saturating_sub(4).max(8);
    let mut body: Vec<Line> = Vec::new();
    let n = plan.steps.len();
    let what = match plan.kind {
        PlanKind::Fix => "PLAN",
        PlanKind::Undo => "UNDO",
        PlanKind::Restart => "RESTART",
    };
    let (risk, rt) = plan.risk();
    body.push(Line::from(vec![
        Span::styled(
            format!(
                "{what}{}{n} step{}",
                dot(look),
                if n == 1 { "" } else { "s" }
            ),
            bold(p.soft),
        ),
        Span::styled(format!("   risk: {risk}"), st(tone(look, rt))),
    ]));
    body.extend(widgets::wrap_hanging(
        &plan.backed(),
        iw as u16,
        "",
        "",
        st(p.muted),
    ));
    body.push(Line::from(""));
    for s in &plan.steps {
        let (mark, c) = match (s.state, look.ascii) {
            (StepState::Done, false) => ("✓ ", p.primary),
            (StepState::Done, true) => ("[x] ", p.primary),
            (StepState::Running, false) => ("◌ ", p.warn),
            (StepState::Running, true) => ("[~] ", p.warn),
            (StepState::Failed, false) => ("✕ ", p.danger),
            (StepState::Failed, true) => ("[!] ", p.danger),
            (StepState::Skipped, false) => ("– ", p.faint),
            (StepState::Skipped, true) => ("[-] ", p.faint),
            (_, false) => ("○ ", p.faint),
            (_, true) => ("[ ] ", p.faint),
        };
        let typed = if s.prop.typed() && plan.state == PlanState::Open {
            if s.prop.needs == "passphrase" {
                "  (asks for the passphrase)".to_string()
            } else {
                format!("  (type {} to approve)", s.prop.confirm)
            }
        } else {
            String::new()
        };
        let text_c = if s.state == StepState::Skipped {
            p.faint
        } else {
            p.text
        };
        let rest = " ".repeat(mark.chars().count());
        let mut l = widgets::wrap_hanging(
            &format!("{}{typed}", s.prop.title),
            iw as u16,
            mark,
            &rest,
            st(text_c),
        );
        if let Some(first) = l.first_mut()
            && let Some(m) = first.spans.first_mut()
        {
            m.style = st(c);
        }
        body.extend(l);
        if !s.result.is_empty() && matches!(s.state, StepState::Done | StepState::Failed) {
            body.extend(widgets::wrap_hanging(
                &s.result,
                iw as u16,
                &rest,
                &rest,
                st(if s.state == StepState::Failed {
                    p.danger
                } else {
                    p.faint
                }),
            ));
        }
        if plan.diff && plan.state == PlanState::Open && !s.prop.change.is_empty() {
            for cl in s.prop.change.lines() {
                let c = if cl.starts_with('-') {
                    p.danger
                } else if cl.starts_with('+') {
                    p.primary
                } else {
                    p.muted
                };
                body.extend(widgets::wrap_hanging(
                    cl,
                    iw as u16,
                    &format!("{rest}  "),
                    &format!("{rest}    "),
                    st(c),
                ));
            }
        }
    }
    body.push(Line::from(""));
    let applying = plan
        .steps
        .iter()
        .position(|s| s.state == StepState::Running);
    match plan.state {
        PlanState::Applying => {
            let k = applying.map_or(0, |i| i + 1);
            let mut l = widgets::sweep(look, None, app.tick, (iw as u16).min(20));
            l.spans.push(Span::styled(
                format!("  applying step {k} of {n}"),
                st(p.muted),
            ));
            body.push(l);
        }
        PlanState::Applied => {
            let text = match plan.kind {
                PlanKind::Fix => "Done. Restart to check it works.",
                PlanKind::Undo => "Put back.",
                PlanKind::Restart => "Restarting.",
            };
            body.extend(widgets::wrap_hanging(
                text,
                iw as u16,
                &format!("{} ", Icon::Check.of(look)),
                "  ",
                st(p.primary),
            ));
        }
        PlanState::Stopped => body.extend(widgets::wrap_hanging(
            "Stopped: the steps without a tick didn't run.",
            iw as u16,
            "",
            "",
            st(p.warn),
        )),
        PlanState::NotNow => body.push(Line::from(Span::styled(
            "Not now: nothing was changed.",
            st(p.muted),
        ))),
        PlanState::Open => {}
    }
    let buttons = plan.buttons();
    if !buttons.is_empty() && plan.state != PlanState::Applying {
        let sel = plan.button.min(buttons.len() - 1);
        let spans: Vec<Span> = buttons
            .iter()
            .enumerate()
            .map(|(i, b)| {
                let (icon, words) = match b {
                    Button::Apply => (Icon::Check, "Apply (a)".to_string()),
                    Button::Changes => (
                        Icon::Search,
                        format!(
                            "{} the changes (d)",
                            if plan.diff { "Hide" } else { "Show" }
                        ),
                    ),
                    Button::NotNow => (Icon::Cross, "Not now (n)".to_string()),
                    Button::Restart => (Icon::Power, "Restart now (r)".to_string()),
                    Button::Undo => (Icon::Rollback, "Undo (u)".to_string()),
                };
                let lit = i == sel && (focused || plan.state == PlanState::Open);
                if lit {
                    Span::styled(
                        format!(" {} {words} ", icon.of(look)),
                        Style::new()
                            .bg(p.selection)
                            .fg(p.primary)
                            .add_modifier(Modifier::BOLD),
                    )
                } else {
                    Span::styled(format!("[ {} {words} ]", icon.of(look)), st(p.soft))
                }
            })
            .collect();
        let total: usize = spans.iter().map(|s| s.width() + 2).sum();
        if bp == Breakpoint::Tiny || total > iw {
            for s in spans {
                let s = Span::styled(layout::truncate(&s.content, iw, look.ascii), s.style);
                body.push(Line::from(s));
            }
        } else {
            let mut row = Vec::new();
            for s in spans {
                row.push(s);
                row.push(Span::raw("  "));
            }
            body.push(Line::from(row));
        }
        if plan.state == PlanState::Open && app.paired() {
            body.extend(widgets::wrap_hanging(
                "also waiting on your phone: approve there or here",
                iw as u16,
                &format!("{} ", Icon::Remote.of(look)),
                "  ",
                st(p.faint),
            ));
        }
    }
    // the frame
    let edge = st(if focused { p.primary } else { p.dim });
    let (tl, tr, bl, br, h, v) = if look.ascii {
        ("+", "+", "+", "+", "-", "|")
    } else {
        ("╭", "╮", "╰", "╯", "─", "│")
    };
    let mut out = vec![Line::from(Span::styled(
        format!("{tl}{}{tr}", h.repeat(iw + 2)),
        edge,
    ))];
    for l in body {
        let pad = iw.saturating_sub(l.width());
        let mut spans = vec![Span::styled(format!("{v} "), edge)];
        spans.extend(l.spans);
        spans.push(Span::raw(" ".repeat(pad)));
        spans.push(Span::styled(format!(" {v}"), edge));
        out.push(Line::from(spans));
    }
    out.push(Line::from(Span::styled(
        format!("{bl}{}{br}", h.repeat(iw + 2)),
        edge,
    )));
    out
}

/// The conversation's panel: the messages (scrolling), the suggestions as chips where the
/// right column is folded away, and the composer.
fn draw_conversation(f: &mut Frame, area: Rect, app: &App, bp: Breakpoint) {
    let look = &app.look;
    let p = &look.pal;
    let active = matches!(app.focus, Focus::Composer | Focus::Plan);
    let inner = boxed(f, area, look, Icon::Vector, "Conversation", active);
    let chips_h = u16::from(bp != Breakpoint::Wide && !app.suggestions.is_empty());
    let [msgs, chips, rule, composer] = Layout::vertical([
        Constraint::Min(1),
        Constraint::Length(chips_h),
        Constraint::Length(1),
        Constraint::Length(1),
    ])
    .areas(inner);
    let lines = conversation(app, msgs.width, bp);
    let (h, total) = (msgs.height as usize, lines.len());
    app.page.set((h, total));
    let back = app.back.min(total.saturating_sub(h));
    let offset = total.saturating_sub(h + back);
    f.render_widget(Paragraph::new(lines).scroll((offset as u16, 0)), msgs);
    if chips_h > 0 {
        let sel = match app.focus {
            Focus::Asking(i) => Some(i),
            _ => None,
        };
        let mut spans = Vec::new();
        for (i, q) in app.suggestions.iter().enumerate() {
            let style = if sel == Some(i) {
                Style::new()
                    .bg(p.selection)
                    .fg(p.white)
                    .add_modifier(Modifier::BOLD)
            } else {
                Style::new().bg(p.panel).fg(p.soft)
            };
            spans.push(Span::styled(
                format!(" {} ", layout::truncate(q, 40, look.ascii)),
                style,
            ));
            spans.push(Span::raw(" "));
        }
        let label = Span::styled(format!("{} ", Icon::Suggest.of(look)), st(p.accent));
        let row = fit_row(
            spans,
            sel.map(|i| i * 2),
            (chips.width as usize).saturating_sub(label.width()),
            look,
        );
        let mut l = vec![label];
        l.extend(row.spans);
        f.render_widget(Paragraph::new(Line::from(l)), chips);
    }
    let rch = if look.ascii { "-" } else { "─" };
    f.render_widget(
        Paragraph::new(Span::styled(rch.repeat(rule.width as usize), st(p.dim))),
        rule,
    );
    // more above: on the panel's top edge; more below: on the composer's rule (never over
    // the conversation itself)
    let (up, down) = if look.ascii {
        (" ^ more ", " v more ")
    } else {
        (" ↑ more ", " ↓ more ")
    };
    let mark = |f: &mut Frame, y: u16, text: &str| {
        let w = text.chars().count() as u16;
        if area.width > w + 24 {
            let r = Rect::new(area.right() - w - 2, y, w, 1);
            f.render_widget(
                Paragraph::new(Span::styled(text.to_string(), st(p.accent))),
                r,
            );
        }
    };
    if offset > 0 {
        mark(f, area.y, up);
    }
    if back > 0 {
        mark(f, rule.y, down);
    }
    // the composer: Ask | Fix, the prompt, what's typed
    let on = Style::new()
        .bg(p.selection)
        .fg(p.primary)
        .add_modifier(Modifier::BOLD);
    let mut spans = vec![
        Span::styled(" Ask ", if app.fix { st(p.muted) } else { on }),
        Span::styled(" Fix ", if app.fix { on } else { st(p.muted) }),
        Span::styled(if look.ascii { " > " } else { " ❯ " }, st(p.primary)),
    ];
    let used: usize = spans.iter().map(|s| s.width()).sum();
    let tail = "/ for commands";
    let room = (composer.width as usize).saturating_sub(used + 1);
    let cursor = if app.focus == Focus::Composer && !app.busy && app.mode == Mode::Chat {
        if look.ascii { "_" } else { "▏" }
    } else {
        ""
    };
    if app.input.is_empty() {
        let ph = if app.fix {
            "Say what's wrong; he'll plan the fix"
        } else {
            "Ask anything about this computer"
        };
        let ph = format!("{ph}{}", ell(look));
        let show_tail = room >= ph.chars().count() + tail.len() + 4;
        let ph = layout::truncate(&ph, room.saturating_sub(1), look.ascii);
        spans.push(Span::styled(cursor, st(p.primary)));
        spans.push(Span::styled(ph.clone(), st(p.faint)));
        if show_tail {
            let gap = room.saturating_sub(ph.chars().count() + tail.len() + 1);
            spans.push(Span::raw(" ".repeat(gap)));
            spans.push(Span::styled(tail, st(p.dim)));
        }
    } else {
        // the end of what's typed, where it's longer than the room
        let chars: Vec<char> = app.input.chars().collect();
        let keep = room.saturating_sub(2);
        let start = chars.len().saturating_sub(keep);
        let shown: String = chars[start..].iter().collect();
        spans.push(Span::styled(shown, st(p.white)));
        spans.push(Span::styled(cursor, st(p.primary)));
    }
    f.render_widget(Paragraph::new(Line::from(spans)), composer);
    if app.focus == Focus::Composer && app.input.starts_with('/') {
        draw_commands(f, msgs, app);
    }
}

/// What `/` offers, over the bottom of the conversation.
fn draw_commands(f: &mut Frame, area: Rect, app: &App) {
    let look = &app.look;
    let p = &look.pal;
    let typed = app.input.split(' ').next().unwrap_or("");
    let list: Vec<&(&str, &str)> = COMMANDS
        .iter()
        .filter(|c| c.0.starts_with(typed) || typed == "/")
        .collect();
    if list.is_empty() {
        return;
    }
    let h = (list.len() as u16 + 2).min(area.height);
    let w = 44.min(area.width);
    let r = Rect::new(area.x, area.bottom() - h, w, h);
    f.render_widget(Clear, r);
    let inner = boxed(f, r, look, Icon::List, "Commands", true);
    let lines: Vec<Line> = list
        .iter()
        .map(|(c, what)| {
            Line::from(vec![
                Span::styled(format!("{c:<11}"), st(p.soft)),
                Span::styled(
                    layout::truncate(what, (inner.width as usize).saturating_sub(11), look.ascii),
                    st(p.muted),
                ),
            ])
        })
        .collect();
    f.render_widget(Paragraph::new(lines), inner);
}

/// A step's typed approval, over the conversation: the same dialogs as ever.
fn draw_typed(f: &mut Frame, area: Rect, app: &App, pi: usize, si: usize, typed: &str) {
    let look = &app.look;
    let plan = &app.plans[pi];
    let prop = &plan.steps[si].prop;
    let detail = format!(
        "Step {} of {} of the plan. VECTOR proposes this; nothing has changed yet for this step.\n\n{}\n\nThis is exactly what will change:\n{}",
        si + 1,
        plan.steps.len(),
        prop.title,
        prop.change
    );
    let h = widgets::text_height(&detail, 64) + 8;
    let r = layout::dialog(area, 72.min(area.width), h.min(area.height));
    if prop.needs == "passphrase" {
        widgets::input(
            f,
            r,
            look,
            &format!("Approve: {}", prop.title),
            &format!("{detail}\n\nType the disk's passphrase to approve; ESC stops here."),
            typed,
            true,
        );
    } else {
        widgets::typed_confirm(
            f,
            r,
            look,
            &format!("Approve: {}", prop.title),
            &detail,
            &prop.confirm,
            typed,
        );
    }
}

/// `c` on a plan: each step's exact change, as the engine saved it (the copy that runs).
fn draw_commands_sheet(f: &mut Frame, area: Rect, app: &App, pi: usize) {
    let look = &app.look;
    let p = &look.pal;
    let r = layout::dialog(
        area,
        84.min(area.width),
        area.height.saturating_sub(2).max(10).min(area.height),
    );
    let inner = widgets::panel(
        f,
        r,
        look,
        &format!("{} COMMANDS · THE PLAN", Icon::List.of(look)),
        None,
    );
    let w = inner.width;
    let mut lines: Vec<Line> = Vec::new();
    for (i, step) in app.plans[pi].steps.iter().enumerate() {
        lines.extend(widgets::wrap_hanging(
            &step.prop.title,
            w,
            &format!("{}. ", i + 1),
            "   ",
            bold(p.soft),
        ));
        for cl in step.prop.change.lines() {
            let c = if cl.starts_with('-') {
                p.danger
            } else if cl.starts_with('+') {
                p.primary
            } else {
                p.text
            };
            lines.extend(widgets::wrap_hanging(cl, w, "   ", "     ", st(c)));
        }
        lines.extend(widgets::wrap_hanging(
            &format!(
                "saved as /run/bromigos-fieldkit/vector/approvals/{}.json",
                step.prop.id
            ),
            w,
            "   ",
            "   ",
            st(p.faint),
        ));
        lines.push(Line::from(""));
    }
    lines.extend(widgets::wrap_hanging(
        "Exactly what Apply changes, step by step. y copies it · Esc closes",
        w,
        "",
        "",
        st(p.muted),
    ));
    layout::scroll_view(f, inner, look, lines, 0);
}

/// `?`: his rules, the keys, the commands, his brain's order.
fn draw_help(f: &mut Frame, area: Rect, app: &App) {
    let look = &app.look;
    let p = &look.pal;
    let r = layout::dialog(area, 64.min(area.width), 30.min(area.height));
    let inner = widgets::panel(
        f,
        r,
        look,
        &format!("{} HIS RULES · KEYS", Icon::Shield.of(look)),
        None,
    );
    let w = inner.width;
    let mut lines: Vec<Line> = Vec::new();
    for rule in RULES {
        lines.extend(widgets::wrap_hanging(rule, w, "  ", "  ", st(p.soft)));
    }
    lines.push(Line::from(""));
    for (k, what) in [
        ("Enter", "ask (Fix: he plans the fix)"),
        ("Shift+Tab", "Ask or Fix"),
        ("Tab", "the plan, what he sees, questions"),
        ("a d n", "apply, the changes, not now"),
        ("r u", "restart, undo (after a plan)"),
        ("PgUp PgDn", "scroll the conversation"),
        ("c", "the plan's exact commands, to copy"),
        ("Alt+X", "a shell; exit it to come back here"),
        ("Ctrl+P", "pair with BRODEC"),
        ("Esc", "back to Home"),
    ] {
        lines.push(Line::from(vec![
            Span::styled(format!("  {k:<11}"), st(p.soft)),
            Span::styled(
                layout::truncate(what, (w as usize).saturating_sub(13), look.ascii),
                st(p.muted),
            ),
        ]));
    }
    lines.push(Line::from(""));
    for (c, what) in COMMANDS.iter().take(7) {
        lines.push(Line::from(vec![
            Span::styled(format!("  {c:<11}"), st(p.soft)),
            Span::styled(
                layout::truncate(what, (w as usize).saturating_sub(13), look.ascii),
                st(p.muted),
            ),
        ]));
    }
    if let Some(c) = app.status["candidates"].as_array() {
        let names: Vec<&str> = c.iter().filter_map(|x| x.as_str()).collect();
        lines.push(Line::from(""));
        lines.extend(widgets::wrap_hanging(
            &format!(
                "His brain, tried in order: {}",
                if names.is_empty() {
                    "nothing set up".to_string()
                } else {
                    names.join(", ")
                }
            ),
            w,
            "",
            "",
            st(p.muted),
        ));
    }
    layout::scroll_view(f, inner, look, lines, 0);
}

/// VECTOR's screen until the person leaves it (Esc). `engine` is fieldkit-engine. It takes the
/// terminal itself: the caller hands it over as it does to an outside program.
pub fn run(look: &Look, engine: &Path) -> io::Result<()> {
    let mut terminal = ratatui::init();
    let _ = execute!(io::stdout(), EnableMouseCapture);
    let mut app = App::new(*look, engine);
    app.refresh_status();
    let result = (|| -> io::Result<()> {
        while !app.done {
            app.pump();
            if app.pairing {
                app.pairing = false;
                pair::pair_in(&mut terminal, &app.look, &app.engine)?;
                app.refresh_status();
            }
            if app.shell {
                app.shell = false;
                let _ = execute!(io::stdout(), DisableMouseCapture);
                ratatui::restore();
                print!("\x1b[2J\x1b[H");
                let _ = io::Write::flush(&mut io::stdout());
                let sh = std::env::var("SHELL").unwrap_or_else(|_| "/bin/bash".into());
                if let Err(e) = Command::new(&sh).arg("-l").status() {
                    eprintln!("{sh}: {e}");
                    thread::sleep(Duration::from_secs(2));
                }
                terminal = ratatui::init();
                let _ = execute!(io::stdout(), EnableMouseCapture);
                terminal.clear()?;
                app.refresh_status();
            }
            if let Some(text) = app.copy.take() {
                print!("\x1b]52;c;{}\x07", crate::fieldkit::base64(text.as_bytes()));
                let _ = io::Write::flush(&mut io::stdout());
            }
            terminal.draw(|f| draw(f, &app))?;
            if event::poll(Duration::from_millis(120))? {
                match event::read()? {
                    Event::Key(k) if k.kind == KeyEventKind::Press => app.key(k.code, k.modifiers),
                    Event::Mouse(m) => match m.kind {
                        MouseEventKind::ScrollUp => app.wheel(false),
                        MouseEventKind::ScrollDown => app.wheel(true),
                        _ => {}
                    },
                    _ => {}
                }
            } else if app.look.motion {
                app.tick = app.tick.wrapping_add(1);
            }
        }
        Ok(())
    })();
    let _ = execute!(io::stdout(), DisableMouseCapture);
    ratatui::restore();
    result
}

#[cfg(test)]
mod tests;
