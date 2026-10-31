//! The VECTOR screen against a stand-in engine: the layouts at every size, the plan card and
//! its approvals (nothing runs before Apply; a typed word where it always was), undo, restart,
//! the composer's commands, what he's looking at, the console and ASCII looks.

use super::*;
use ratatui::Terminal;
use ratatui::backend::TestBackend;
use std::os::unix::fs::PermissionsExt;

const PLAN_REPLY: &str = r#"{"ok": true, "brain": {"source": "the lab (llm)", "url": "http://10.0.0.5:4000/v1", "model": "qwen3-32b", "host": "node-a", "lan": true}, "switch_off": false, "looked_at": ["this computer", "last boot's log", "the black screen checks"], "reply": "Two things stopped the login screen. A setting file that looks switched off is still being read, and the startup files ask for a driver name that doesn't exist. Here's the plan:", "proposals": [{"id": "0123456789ab", "tool": "fix", "title": "Move 10-gpu.conf.disabled out of /etc/sddm.conf.d", "change": "- /etc/sddm.conf.d/10-gpu.conf.disabled\nField Kit keeps a backup of everything it changes.", "confirm": "", "needs": ""}, {"id": "abcdef012345", "tool": "fix", "title": "Change MODULES=(nvidia-open) to MODULES=(nvidia)", "change": "- MODULES=(nvidia-open)\n+ MODULES=(nvidia)", "confirm": "", "needs": ""}]}"#;

const NO_BRAIN_REPLY: &str = r#"{"ok": true, "brain": null, "switch_off": false, "looked_at": ["last boot's log"], "reply": "No brain on this line yet, so I can only read you Field Kit's own findings. Protocol is wise.\nWhat Field Kit found:\n- A login screen setting left in /etc/sddm.conf.d/10-gpu.conf.disabled: SDDM reads every file in that folder whatever its name.\nTo give me a brain: connect to your lab (Lab › Network settings) with the lab's connection on the stick (fieldkit/homelab.toml).", "proposals": []}"#;

/// A stand-in engine: `engine vector VERB …` answers from canned replies, and records what
/// it was asked to run, decline and undo.
fn fake_engine(dir: &Path, brain: bool) -> PathBuf {
    let p = dir.join("fieldkit-engine");
    let brain_json = if brain {
        r#"{"source": "the lab (llm)", "url": "http://10.0.0.5:4000/v1", "model": "qwen3-32b", "host": "node-a", "lan": true}"#
    } else {
        "null"
    };
    let status = format!(
        r#"{{"ok": true, "brain": {brain_json}, "switch_off": false, "persona": "the vector package", "candidates": ["the lab (llm)"], "pending": 0, "brodec": "{}", "no_internet": true, "context": [{{"key": "last_boot", "label": "last boot's log", "on": true}}, {{"key": "install", "label": "nvme0n1p2 · mounted", "on": true}}, {{"key": "findings", "label": "repair findings", "on": true}}]}}"#,
        if brain { "paired" } else { "missing" }
    );
    let suggest = r#"{"ok": true, "questions": ["Why won't it start properly?", "Is any disk about to fail?", "What changed in the last update?", "Why is Windows asking for a BitLocker key?", "Make this computer a lab node"]}"#;
    let undo = r#"{"ok": true, "proposal": {"id": "undo00000001", "tool": "undo", "title": "Undo: Move 10-gpu.conf.disabled out of /etc/sddm.conf.d", "change": "Puts these back from Field Kit's backups (20261030-101010-sddm-dropin):\n  /etc/sddm.conf.d/10-gpu.conf.disabled", "confirm": "", "needs": ""}}"#;
    let reboot = r#"{"ok": true, "proposal": {"id": "reboot000001", "tool": "control", "title": "Restart this computer", "change": "systemctl reboot", "confirm": "reboot", "needs": ""}}"#;
    std::fs::write(dir.join("status.json"), status).unwrap();
    std::fs::write(dir.join("suggest.json"), suggest).unwrap();
    std::fs::write(
        dir.join("ask.json"),
        if brain { PLAN_REPLY } else { NO_BRAIN_REPLY },
    )
    .unwrap();
    std::fs::write(dir.join("undo.json"), undo).unwrap();
    std::fs::write(dir.join("control.json"), reboot).unwrap();
    std::fs::write(
        &p,
        format!(
            "#!/bin/sh\nd={d}\ncase \"$3\" in\n  ask) cat > $d/asked.json ;;\n  *) cat >/dev/null ;;\nesac\ncase \"$3\" in\n  \
             status|suggest|ask|undo|control|pending) cat $d/$3.json ;;\n  \
             run) echo \"$4 $6\" >> $d/ran; echo '{{\"ok\": true, \"message\": \"Done here.\"}}' ;;\n  \
             decide) echo \"$4 $5\" >> $d/declined; echo '{{\"ok\": true}}' ;;\n  \
             add) case \"$4\" in /etc/shadow) echo '{{\"ok\": false, \"message\": \"Refused: VECTOR never reads secrets.\"}}' ;; \
             *) echo \"{{\\\"ok\\\": true, \\\"path\\\": \\\"$4\\\", \\\"label\\\": \\\"$(basename $4)\\\"}}\" ;; esac ;;\nesac\n",
            d = dir.display(),
        ),
    )
    .unwrap();
    std::fs::set_permissions(&p, std::fs::Permissions::from_mode(0o755)).unwrap();
    p
}

/// Takes the engine's replies until `done` holds (at most thirty seconds: a loaded machine
/// runs the stand-in engine slowly).
fn wait(app: &mut App, done: impl Fn(&App) -> bool) {
    for _ in 0..3000 {
        app.pump();
        if done(app) {
            return;
        }
        thread::sleep(Duration::from_millis(10));
    }
    panic!("the engine's reply never came");
}

fn wait_file(path: &Path, done: impl Fn(&str) -> bool) -> String {
    for _ in 0..3000 {
        let s = std::fs::read_to_string(path).unwrap_or_default();
        if done(&s) {
            return s;
        }
        thread::sleep(Duration::from_millis(10));
    }
    panic!("{} never came", path.display());
}

fn settle(app: &mut App) {
    wait(app, |a| {
        let running = a
            .plans
            .iter()
            .any(|p| p.steps.iter().any(|s| s.state == StepState::Running));
        !a.busy && !running && a.status.get("ok").is_some() && !a.suggestions.is_empty()
    });
}

fn rows(app: &App, w: u16, h: u16) -> Vec<String> {
    let mut t = Terminal::new(TestBackend::new(w, h)).unwrap();
    t.draw(|f| draw(f, app)).unwrap();
    let b = t.backend().buffer().clone();
    (0..b.area.height)
        .map(|y| {
            (0..b.area.width)
                .map(|x| b[(x, y)].symbol().to_string())
                .collect()
        })
        .collect()
}

fn render(app: &App, w: u16, h: u16) -> String {
    rows(app, w, h).join("\n") + "\n"
}

/// The screens as text, for looking at: into $BROMIGOS_FIELDKIT_SHOTS when it's set.
fn shot(name: &str, text: &str) {
    if let Some(dir) = std::env::var_os("BROMIGOS_FIELDKIT_SHOTS") {
        let _ = std::fs::write(Path::new(&dir).join(name), text);
    }
}

fn typed(app: &mut App, s: &str) {
    for c in s.chars() {
        app.key(KeyCode::Char(c), KeyModifiers::NONE);
    }
}

fn key(app: &mut App, k: KeyCode) {
    app.key(k, KeyModifiers::NONE);
}

fn ask(app: &mut App, q: &str) {
    typed(app, q);
    key(app, KeyCode::Enter);
    settle(app);
}

fn app_with(dir: &Path, brain: bool, look: Look) -> App {
    let mut app = App::new(look, &fake_engine(dir, brain));
    app.refresh_status();
    settle(&mut app);
    app
}

/// The conversation's frame is whole on every row: nothing drew over its edges.
fn frame_whole(r: &[String]) -> Result<(), String> {
    let top = r
        .iter()
        .position(|l| l.contains("CONVERSATION"))
        .ok_or("no conversation panel")?;
    let line: Vec<char> = r[top].chars().collect();
    let title_at = r[top][..r[top].find("CONVERSATION").unwrap()]
        .chars()
        .count();
    let corner = |c: &char| *c == '╭' || *c == '╮' || *c == '+';
    let left = line[..title_at]
        .iter()
        .rposition(corner)
        .ok_or("no left corner")?;
    let right = line[title_at..]
        .iter()
        .position(corner)
        .map(|i| i + title_at)
        .ok_or("no right corner")?;
    let mut y = top + 1;
    loop {
        let l: Vec<char> = r.get(y).ok_or("ran off the screen")?.chars().collect();
        if l[left] == '╰' || (l[left] == '+' && l[right] == '+') {
            if l[right] != '╯' && l[right] != '+' {
                return Err(format!("row {y}: bottom right corner is {:?}", l[right]));
            }
            return Ok(());
        }
        if !matches!(l[left], '│' | '|') || !matches!(l[right], '│' | '|') {
            return Err(format!(
                "row {y}: edges are {:?} {:?}\n{}",
                l[left],
                l[right],
                r.join("\n")
            ));
        }
        y += 1;
    }
}

#[test]
fn every_size_lays_out_whole() {
    let d = tempfile::tempdir().unwrap();
    let mut app = app_with(d.path(), true, Look::wick());
    ask(
        &mut app,
        "it won't get past a black screen with a blinking cursor",
    );
    for (w, h) in [
        (200, 55),
        (150, 45),
        (120, 35),
        (80, 24),
        (60, 30),
        (40, 15),
    ] {
        let r = rows(&app, w, h);
        let s = r.join("\n");
        assert_eq!(r.len(), h as usize);
        assert!(r.iter().all(|l| l.chars().count() == w as usize), "{w}x{h}");
        frame_whole(&r).unwrap_or_else(|e| panic!("{w}x{h}: {e}\n{s}"));
        assert!(s.contains("V E C T O R"), "{w}x{h}\n{s}");
        assert!(s.contains(" Ask ") && s.contains(" Fix "), "{w}x{h}\n{s}");
        let bp = Breakpoint::of(w);
        assert_eq!(
            s.contains("TRY ASKING"),
            bp == Breakpoint::Wide,
            "{w}x{h}\n{s}"
        );
        assert_eq!(s.contains("HIS RULES"), bp == Breakpoint::Wide, "{w}x{h}");
        assert_eq!(s.contains("LOOKING AT"), bp.side_by_side(), "{w}x{h}");
        if bp == Breakpoint::Tiny {
            assert!(
                !s.contains("brain: lab"),
                "icons only on a Tiny screen\n{s}"
            );
        } else {
            assert!(s.contains("brain: lab · node-a"), "{w}x{h}\n{s}");
            assert!(
                s.contains("BRODEC: paired") && s.contains("no internet used"),
                "{w}x{h}\n{s}"
            );
        }
        // a tall enough screen shows the plan and its buttons; a short one scrolls to them
        if h >= 30 {
            assert!(s.contains("Apply (a)"), "{w}x{h}\n{s}");
        }
    }
    shot("tui-vector-150.txt", &render(&app, 150, 45));
    shot("tui-vector-110.txt", &render(&app, 110, 35));
    shot("tui-vector-80.txt", &render(&app, 80, 24));
    shot("tui-vector-60.txt", &render(&app, 60, 30));
    // under 40×15: make the window bigger
    assert!(render(&app, 39, 20).contains("Make the window bigger"));
}

#[test]
fn a_tiny_screen_stacks_the_plan_buttons() {
    let d = tempfile::tempdir().unwrap();
    let mut app = app_with(d.path(), true, Look::wick());
    ask(&mut app, "black screen");
    let r = rows(&app, 60, 40);
    let apply = r.iter().position(|l| l.contains("Apply (a)")).unwrap();
    assert!(r[apply + 1].contains("the changes (d)"), "{}", r.join("\n"));
    assert!(r[apply + 2].contains("Not now (n)"));
}

#[test]
fn the_conversation_scrolls_and_keeps_its_place() {
    let d = tempfile::tempdir().unwrap();
    let mut app = app_with(d.path(), false, Look::wick());
    for i in 0..6 {
        ask(&mut app, &format!("question number {i}"));
    }
    let s = render(&app, 80, 24);
    assert!(s.contains("homelab.toml"), "the newest shows\n{s}");
    assert!(s.contains("↑ more"));
    key(&mut app, KeyCode::PageUp);
    let s = render(&app, 80, 24);
    assert!(s.contains("↓ more"), "{s}");
    let back = app.back;
    assert!(back > 0);
    // a resize keeps the place (rows up from the end)
    let _ = render(&app, 150, 45);
    assert_eq!(app.back, back);
    app.wheel(true);
    app.wheel(true);
    app.wheel(true);
    app.wheel(true);
    key(&mut app, KeyCode::PageDown);
    key(&mut app, KeyCode::PageDown);
    assert_eq!(app.back, 0);
}

#[test]
fn no_brain_explains_and_says_how_to_give_him_one() {
    let d = tempfile::tempdir().unwrap();
    let mut app = app_with(d.path(), false, Look::wick());
    ask(&mut app, "why is my screen black?");
    let s = render(&app, 150, 45);
    shot("tui-vector.txt", &s);
    assert!(s.contains("brain: none · findings only"), "{s}");
    assert!(s.contains("To give me a brain"), "{s}");
    assert!(s.contains("looked at: last boot's log"), "{s}");
    assert!(s.contains("BRODEC: not paired"), "{s}");
    assert!(s.contains("Why won't it start properly?"), "{s}");
    assert!(s.contains("never money, never secrets"), "{s}");
    assert!(app.plans.is_empty());
    // the emergency switch, plainly both ways
    assert!(s.contains("emergency switch: off · he can act"), "{s}");
    app.status["switch_off"] = json!(true);
    let s = render(&app, 150, 45);
    assert!(s.contains("EMERGENCY SWITCH ON · he only talks"), "{s}");
    assert!(s.contains("emergency switch on · only talks"), "{s}");
}

#[test]
fn a_plan_runs_only_after_apply_and_not_now_runs_nothing() {
    let d = tempfile::tempdir().unwrap();
    let mut app = app_with(d.path(), true, Look::wick());
    ask(&mut app, "it won't get past a black screen");
    let asked: Value =
        serde_json::from_str(&std::fs::read_to_string(d.path().join("asked.json")).unwrap())
            .unwrap();
    assert_eq!(asked["mode"], "ask");
    assert_eq!(asked["context"]["last_boot"], true);
    assert_eq!(app.focus, Focus::Plan);
    assert_eq!(app.state().0, "waiting for you");
    let s = render(&app, 150, 45);
    shot("tui-vector-approval.txt", &s);
    assert!(s.contains("PLAN · 2 steps"), "{s}");
    assert!(s.contains("risk: low"), "{s}");
    assert!(s.contains("Field Kit's backups"), "{s}");
    assert!(!s.contains("14 days"));
    assert!(
        s.contains("+ MODULES=(nvidia)"),
        "the exact changes show first\n{s}"
    );
    assert!(s.contains("also waiting on your phone"), "{s}");
    assert!(
        s.contains("looked at: this computer · last boot's log · the black screen checks"),
        "{s}"
    );
    assert!(
        !d.path().join("ran").exists(),
        "nothing runs before approval"
    );
    // d hides the changes, d shows them again
    key(&mut app, KeyCode::Char('d'));
    assert!(!render(&app, 150, 45).contains("+ MODULES=(nvidia)"));
    key(&mut app, KeyCode::Char('d'));
    // Not now: nothing runs, the engine hears both declined
    key(&mut app, KeyCode::Char('n'));
    settle(&mut app);
    assert_eq!(app.plans[0].state, PlanState::NotNow);
    assert!(!d.path().join("ran").exists());
    let declined = wait_file(&d.path().join("declined"), |s| s.lines().count() >= 2);
    assert!(declined.contains("0123456789ab deny") && declined.contains("abcdef012345 deny"));
    assert!(render(&app, 150, 45).contains("Not now: nothing was changed."));
    // Fix mode, asked again: a applies every step, in order
    app.focus = Focus::Composer;
    app.key(KeyCode::BackTab, KeyModifiers::SHIFT);
    assert!(app.fix);
    ask(&mut app, "fix it");
    let asked: Value =
        serde_json::from_str(&std::fs::read_to_string(d.path().join("asked.json")).unwrap())
            .unwrap();
    assert_eq!(asked["mode"], "fix");
    key(&mut app, KeyCode::Char('a'));
    settle(&mut app);
    let ran = std::fs::read_to_string(d.path().join("ran")).unwrap();
    assert_eq!(ran, "0123456789ab local\nabcdef012345 local\n");
    assert_eq!(app.plans[1].state, PlanState::Applied);
    assert_eq!(app.state().0, "done · restart to check it");
    let s = render(&app, 150, 45);
    shot("tui-vector-applied.txt", &s);
    assert!(
        s.contains("Restart now (r)") && s.contains("Undo (u)"),
        "{s}"
    );
    assert!(s.contains("✓ Move 10-gpu.conf.disabled"), "{s}");
    // Undo comes back as its own plan, to approve
    key(&mut app, KeyCode::Char('u'));
    wait(&mut app, |a| a.plans.len() == 3);
    let undo = app.plans.last().unwrap();
    assert_eq!(undo.kind, PlanKind::Undo);
    assert_eq!(undo.state, PlanState::Open);
    assert_eq!(
        std::fs::read_to_string(d.path().join("ran"))
            .unwrap()
            .lines()
            .count(),
        2,
        "undo isn't run before Apply"
    );
    key(&mut app, KeyCode::Enter);
    settle(&mut app);
    assert!(
        std::fs::read_to_string(d.path().join("ran"))
            .unwrap()
            .contains("undo00000001 local")
    );
}

#[test]
fn restart_needs_the_word_typed() {
    let d = tempfile::tempdir().unwrap();
    let mut app = app_with(d.path(), true, Look::wick());
    ask(&mut app, "fix it");
    key(&mut app, KeyCode::Char('a'));
    settle(&mut app);
    key(&mut app, KeyCode::Char('r'));
    wait(&mut app, |a| matches!(a.mode, Mode::Typing { .. }));
    assert!(matches!(app.mode, Mode::Typing { .. }));
    let s = render(&app, 150, 45);
    assert!(s.contains("Type reboot to go ahead"), "{s}");
    key(&mut app, KeyCode::Enter);
    assert!(
        !std::fs::read_to_string(d.path().join("ran"))
            .unwrap()
            .contains("reboot0")
    );
    typed(&mut app, "reboot");
    key(&mut app, KeyCode::Enter);
    settle(&mut app);
    assert!(
        std::fs::read_to_string(d.path().join("ran"))
            .unwrap()
            .contains("reboot000001 local")
    );
}

#[test]
fn a_typed_confirmation_needs_the_word() {
    let d = tempfile::tempdir().unwrap();
    let mut app = app_with(d.path(), true, Look::wick());
    let pi = app.add_plan(Plan::new(
        PlanKind::Fix,
        vec![Proposal {
            id: "0123456789ab".into(),
            tool: "rollback".into(),
            title: "Roll back to snapshot 7".into(),
            change: "The install starts as it was at snapshot 7.".into(),
            confirm: "rollback".into(),
            needs: String::new(),
        }],
    ));
    assert_eq!(app.plans[pi].risk().0, "medium");
    key(&mut app, KeyCode::Char('a'));
    assert!(matches!(app.mode, Mode::Typing { .. }));
    key(&mut app, KeyCode::Char('y')); // typed, not an approval
    key(&mut app, KeyCode::Enter);
    assert!(!d.path().join("ran").exists());
    key(&mut app, KeyCode::Backspace);
    typed(&mut app, "rollback");
    key(&mut app, KeyCode::Enter);
    settle(&mut app);
    assert!(d.path().join("ran").exists());
    // Esc at a typed step stops the plan there
    let pi = app.add_plan(Plan::new(
        PlanKind::Fix,
        vec![Proposal {
            id: "c0ffee000000".into(),
            tool: "run_command".into(),
            title: "Run lsblk".into(),
            confirm: "run".into(),
            ..Default::default()
        }],
    ));
    assert_eq!(app.plans[pi].risk().0, "high");
    assert!(app.plans[pi].backed().contains("nothing backs it up"));
    key(&mut app, KeyCode::Char('a'));
    key(&mut app, KeyCode::Esc);
    assert_eq!(app.plans[pi].state, PlanState::NotNow);
    assert!(
        !std::fs::read_to_string(d.path().join("ran"))
            .unwrap()
            .contains("c0ffee")
    );
}

#[test]
fn commands_and_what_he_looks_at() {
    let d = tempfile::tempdir().unwrap();
    let mut app = app_with(d.path(), true, Look::wick());
    typed(&mut app, "/");
    let s = render(&app, 150, 45);
    assert!(s.contains("/add PATH") && s.contains("/pair"), "{s}");
    key(&mut app, KeyCode::Backspace);
    ask(&mut app, "/add /etc/fstab");
    wait(&mut app, |a| {
        a.ctx.iter().any(|c| c.key == "file:/etc/fstab")
    });
    assert!(
        app.ctx.iter().any(|c| c.key == "file:/etc/fstab" && c.on),
        "{:?}",
        app.ctx
    );
    ask(&mut app, "/add /etc/shadow");
    wait(&mut app, |a| {
        a.msgs.last().is_some_and(|m| m.text.contains("Refused"))
    });
    assert!(
        app.msgs
            .last()
            .unwrap()
            .text
            .contains("never reads secrets")
    );
    assert!(!app.ctx.iter().any(|c| c.key == "file:/etc/shadow"));
    // turn the last boot's log off: it isn't sent
    ask(&mut app, "/look");
    assert_eq!(app.focus, Focus::Looking(0));
    key(&mut app, KeyCode::Char(' '));
    assert_eq!(app.context()["last_boot"], false);
    assert_eq!(app.context()["files"], json!(["/etc/fstab"]));
    let s = render(&app, 150, 45);
    assert!(s.contains("○ last boot's log"), "{s}");
    assert!(s.contains("fstab"), "{s}");
    key(&mut app, KeyCode::Esc);
    ask(&mut app, "/fix");
    assert!(app.fix);
    ask(&mut app, "/pair");
    assert!(app.pairing);
    ask(&mut app, "/rules");
    assert!(app.help);
    assert!(render(&app, 120, 35).contains("never touches the emergency switch"));
    key(&mut app, KeyCode::Esc);
    ask(&mut app, "/clear");
    assert_eq!(app.msgs.len(), 1);
    // a suggested question is asked with Enter
    app.focus = Focus::Asking(1);
    key(&mut app, KeyCode::Enter);
    settle(&mut app);
    assert!(
        app.msgs
            .iter()
            .any(|m| m.text == "Is any disk about to fail?")
    );
}

#[test]
fn reduced_motion_holds_the_orb_still() {
    let d = tempfile::tempdir().unwrap();
    let mut look = Look::wick();
    look.motion = false;
    let mut app = app_with(d.path(), false, look);
    let a = render(&app, 150, 45);
    app.tick = 40;
    assert_eq!(a, render(&app, 150, 45));
    app.look.motion = true;
    app.tick = 0;
    let b = render(&app, 150, 45);
    app.tick = 40;
    assert_ne!(b, render(&app, 150, 45), "the scan goes round");
    assert!(
        b.chars().any(|c| ('\u{2801}'..='\u{28ff}').contains(&c)),
        "a braille orb"
    );
}

#[test]
fn the_console_and_ascii_looks_render() {
    let d = tempfile::tempdir().unwrap();
    let mut look = Look::wick();
    look.ascii = true;
    look.nerd = false;
    look.mode = bromigos_tui::Mode::Ansi16;
    look.pal = look.pal.for_mode(look.mode);
    let mut app = app_with(d.path(), true, look);
    ask(&mut app, "black screen");
    for (w, h) in [(150, 45), (110, 35), (80, 24), (60, 30)] {
        let r = rows(&app, w, h);
        let s = r.join("\n");
        let odd: String = s.chars().filter(|c| !c.is_ascii()).collect();
        assert!(odd.is_empty(), "{w}x{h}: not ASCII: {odd:?}\n{s}");
        frame_whole(&r).unwrap_or_else(|e| panic!("{w}x{h}: {e}\n{s}"));
        assert!(s.contains("V E C T O R"));
    }
    let s = render(&app, 150, 45);
    shot("tui-vector-console.txt", &s);
    assert!(
        s.contains("( (@) )") || s.contains("( (o) )"),
        "the plain ring\n{s}"
    );
    assert!(s.contains("[ ] Move 10-gpu"), "{s}");
}

#[test]
fn c_shows_the_plans_commands_and_alt_x_opens_a_shell() {
    let d = tempfile::tempdir().unwrap();
    let mut app = app_with(d.path(), true, Look::wick());
    ask(&mut app, "black screen");
    // the engine's saved copy (vector pending) is the one shown
    std::fs::write(
        d.path().join("pending.json"),
        r#"{"ok": true, "pending": [{"id": "abcdef012345", "change": "- MODULES=(nvidia-open)\n+ MODULES=(nvidia)\nthen: mkinitcpio -P"}]}"#,
    )
    .unwrap();
    key(&mut app, KeyCode::Char('c'));
    assert_eq!(app.commands, Some(0));
    wait(&mut app, |a| {
        a.plans[0].steps[1].prop.change.contains("mkinitcpio -P")
    });
    let s = render(&app, 150, 45);
    assert!(s.contains("COMMANDS"), "{s}");
    assert!(
        s.contains("then: mkinitcpio -P") && s.contains("approvals/0123456789ab.json"),
        "{s}"
    );
    key(&mut app, KeyCode::Char('y'));
    assert!(
        app.copy
            .as_deref()
            .is_some_and(|t| t.starts_with("1. Move 10-gpu"))
    );
    key(&mut app, KeyCode::Esc);
    assert_eq!(app.commands, None);
    assert!(!d.path().join("ran").exists(), "showing runs nothing");
    // Alt+X: a shell, from the composer too; nothing typed
    app.focus = Focus::Composer;
    app.key(KeyCode::Char('x'), KeyModifiers::ALT);
    assert!(app.shell);
    assert!(app.input.is_empty());
    app.key(KeyCode::Char('r'), KeyModifiers::ALT);
    assert!(app.input.is_empty(), "other Alt keys aren't typed");
}
