//! `bromigos ext`: installs from git repositories made in a temporary directory, the
//! links they get, the ledger, updates (what changed, new permissions), removal, and
//! the refusals (paths out of the extension, symlinks, name clashes, no approval).

use std::collections::HashMap;
use std::fs;
use std::os::unix::fs::{PermissionsExt, symlink};
use std::path::{Path, PathBuf};
use std::process::Command;

use bromigos_core::ext::{self, Approval, InstallOpts, Kind, UpdateOpts};
use bromigos_core::paths::Paths;

struct Sandbox {
    dir: tempfile::TempDir,
}

impl Sandbox {
    fn new() -> Self {
        let s = Sandbox {
            dir: tempfile::tempdir().unwrap(),
        };
        fs::create_dir_all(s.dir.path().join("home")).unwrap();
        fs::create_dir_all(s.dir.path().join("share/themes")).unwrap();
        s
    }
    fn paths(&self) -> Paths {
        let m: HashMap<&str, PathBuf> = [
            ("HOME", self.dir.path().join("home")),
            ("XDG_RUNTIME_DIR", self.dir.path().join("run")),
            ("BROMIGOS_SHARE_DIR", self.dir.path().join("share")),
            ("BROMIGOS_LIB_BIN", self.dir.path().join("libbin")),
        ]
        .into_iter()
        .collect();
        Paths::from_lookup(|k| m.get(k).cloned())
    }
    fn path(&self, rel: &str) -> PathBuf {
        self.dir.path().join(rel)
    }
    /// A starter of `kind` named `name`, committed in its own git repository.
    fn repo(&self, kind: Kind, name: &str) -> PathBuf {
        let d = self.path(&format!("repos/{name}"));
        ext::new_starter(kind, name, &d).unwrap();
        git(&d, &["init", "-q", "-b", "main"]);
        commit(&d, "first");
        d
    }
    fn active(&self, rel: &str) -> PathBuf {
        self.paths().ext_active("").join(rel)
    }
}

fn git(dir: &Path, args: &[&str]) -> String {
    let out = Command::new("git")
        .arg("-C")
        .arg(dir)
        .args(["-c", "user.name=t", "-c", "user.email=t@example.com"])
        .args(args)
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "git {args:?}: {}",
        String::from_utf8_lossy(&out.stderr)
    );
    String::from_utf8_lossy(&out.stdout).trim().to_owned()
}

fn commit(dir: &Path, msg: &str) {
    git(dir, &["add", "-A"]);
    git(dir, &["commit", "-q", "-m", msg]);
}

fn yes(_: &ext::Plan) -> Option<Approval> {
    Some(Approval::Interactive)
}

fn no(_: &ext::Plan) -> Option<Approval> {
    None
}

fn install(s: &Sandbox, src: &Path) -> ext::Result<ext::Report> {
    ext::install(
        &s.paths(),
        &src.to_string_lossy(),
        &InstallOpts::default(),
        &mut yes,
    )
}

#[test]
fn a_theme_installs_without_a_question_and_keeps_its_git() {
    let s = Sandbox::new();
    let repo = s.repo(Kind::Theme, "teal-glass");
    let mut asked = false;
    let r = ext::install(
        &s.paths(),
        &repo.to_string_lossy(),
        &InstallOpts::default(),
        &mut |_| {
            asked = true;
            None
        },
    )
    .unwrap();
    assert!(!asked, "a theme is data: no question");
    let head = git(&repo, &["rev-parse", "HEAD"]);
    assert_eq!(r.commit.as_deref(), Some(head.as_str()));
    let src = s.paths().ext_dir().join("src/teal-glass");
    assert!(
        src.join(".git").is_dir(),
        "the checkout keeps git (it updates)"
    );
    let link = s.active("themes/teal-glass");
    assert_eq!(fs::read_link(&link).unwrap(), src);
    // the theme machinery sees it
    let loc = bromigos_core::theme::Locations::new(&s.paths());
    assert!(bromigos_core::theme::names(&loc).contains(&"teal-glass".to_owned()));
    let l = ext::load_ledger(&s.paths()).unwrap();
    let e = &l.extensions["teal-glass"];
    assert_eq!(e.approved.how, "data-only");
    assert_eq!(e.source.ref_kind, "branch");
    assert_eq!(e.source.git_ref.as_deref(), Some("main"));
    assert!(e.files.contains_key("colors.toml"));
    assert!(l.txn.is_none());
}

#[test]
fn code_needs_a_yes_and_is_linked_into_its_seams() {
    let s = Sandbox::new();
    let repo = s.repo(Kind::VectorTool, "uptime-tool");
    let declined = ext::install(
        &s.paths(),
        &repo.to_string_lossy(),
        &InstallOpts::default(),
        &mut no,
    );
    assert!(declined.unwrap_err().0.contains("declined"));
    assert!(!s.paths().ext_dir().join("src/uptime-tool").exists());
    assert!(ext::load_ledger(&s.paths()).unwrap().extensions.is_empty());

    install(&s, &repo).unwrap();
    let link = s.active("vector/uptime_tool.py");
    let target = fs::read_link(&link).unwrap();
    assert!(target.ends_with("src/uptime-tool/tool.py"), "{target:?}");
    let l = ext::load_ledger(&s.paths()).unwrap();
    let e = &l.extensions["uptime-tool"];
    assert_eq!(e.approved.how, "interactive");
    assert_eq!(e.permissions.vector.as_deref(), Some("read"));
    let lr = &e.parts[0].links[0];
    assert_eq!(lr.link, link);
    assert_eq!(lr.sha256, ext::sha256_file(&target).unwrap());
}

#[test]
fn every_kind_links_where_its_loader_looks() {
    let s = Sandbox::new();
    let want = [
        (Kind::Theme, "k-theme", "themes/k-theme"),
        (Kind::LiveDeck, "k-deck", "live/decks/k-deck.py"),
        (Kind::LiveLayer, "k-layer", "live/layers/k-layer.frag"),
        (Kind::Widget, "k-widget", "widgets/k_widget.py"),
        (Kind::VectorTool, "k-tool", "vector/k_tool.py"),
        (Kind::VectorMemory, "k-memory", "vector/k_memory.py"),
        (Kind::VectorSkill, "k-skill", "skills/k-skill.md"),
        (Kind::HomelabAdapter, "k-adapter", "homelab/k_adapter.py"),
        (Kind::Command, "k-command", "bin/bromigos-k-command"),
        (Kind::Hook, "k-hook", "hooks/theme-set.d/k-hook--theme-set"),
    ];
    for (kind, name, link) in want {
        let repo = s.repo(kind, name);
        install(&s, &repo).unwrap_or_else(|e| panic!("{kind}: {e}"));
        assert!(
            fs::read_link(s.active(link)).is_ok(),
            "{kind}: no link at {link}"
        );
    }
    assert!(s.active("live/layers/k-layer.json").exists());
    // the router finds the command, the theme hooks include the hook
    let p = s.paths();
    let dirs = bromigos_core::commands::search_dirs(&p, None);
    assert!(bromigos_core::commands::find(&dirs, "bromigos-k-command").is_some());
    let hooks = bromigos_core::theme::hooks(&p);
    assert!(
        hooks.iter().any(|h| h.ends_with("k-hook--theme-set")),
        "{hooks:?}"
    );
}

#[test]
fn remove_and_disable_unlink_cleanly() {
    let s = Sandbox::new();
    let repo = s.repo(Kind::Widget, "panel-x");
    install(&s, &repo).unwrap();
    let link = s.active("widgets/panel_x.py");
    assert!(fs::symlink_metadata(&link).is_ok());
    ext::set_enabled(&s.paths(), "panel-x", false).unwrap();
    assert!(fs::symlink_metadata(&link).is_err());
    assert!(s.paths().ext_dir().join("src/panel-x").is_dir());
    ext::set_enabled(&s.paths(), "panel-x", true).unwrap();
    assert!(fs::symlink_metadata(&link).is_ok());
    // a hand edit of the installed copy: enable refuses after a disable
    ext::set_enabled(&s.paths(), "panel-x", false).unwrap();
    fs::write(
        s.paths().ext_dir().join("src/panel-x/widget.py"),
        "print('x')\n",
    )
    .unwrap();
    let e = ext::set_enabled(&s.paths(), "panel-x", true).unwrap_err();
    assert!(e.0.contains("changed since it was installed"), "{e}");
    ext::remove(&s.paths(), "panel-x").unwrap();
    assert!(fs::symlink_metadata(&link).is_err());
    assert!(!s.paths().ext_dir().join("src/panel-x").exists());
    let l = ext::load_ledger(&s.paths()).unwrap();
    assert!(l.extensions.is_empty());
    assert_eq!(l.removed[0].name, "panel-x");
    // nothing else left in the seam
    assert_eq!(fs::read_dir(s.active("widgets")).unwrap().count(), 0);
}

#[test]
fn an_update_shows_changes_and_new_permissions_then_swaps() {
    let s = Sandbox::new();
    let repo = s.repo(Kind::VectorTool, "net-tool");
    install(&s, &repo).unwrap();
    let old = git(&repo, &["rev-parse", "HEAD"]);
    // nothing new: up to date
    let r = ext::update(&s.paths(), "net-tool", &UpdateOpts::default(), &mut no).unwrap();
    assert_eq!(r.op, "current");
    // a new version reaches the network and becomes a desktop-level tool
    let m = repo.join("bromigos-ext.toml");
    let text = fs::read_to_string(&m).unwrap();
    fs::write(
        &m,
        text.replace("version = \"0.1.0\"", "version = \"0.2.0\"")
            .replace("network = \"none\"", "network = [\"api.example.com\"]")
            .replace("vector = \"read\"", "vector = \"desktop\""),
    )
    .unwrap();
    fs::write(repo.join("extra.txt"), "new\n").unwrap();
    commit(&repo, "0.2.0");
    let new = git(&repo, &["rev-parse", "HEAD"]);
    // check only: nothing changes
    let r = ext::update(
        &s.paths(),
        "net-tool",
        &UpdateOpts {
            check_only: true,
            ..Default::default()
        },
        &mut no,
    )
    .unwrap();
    assert_eq!(r.op, "available");
    let ch = r.plan.as_ref().unwrap().changes.as_ref().unwrap();
    assert!(ch.added.contains(&"extra.txt".to_owned()));
    assert!(ch.changed.contains(&"bromigos-ext.toml".to_owned()));
    assert!(
        ch.new_permissions
            .iter()
            .any(|l| l.contains("api.example.com"))
    );
    assert!(ch.new_permissions.iter().any(|l| l.contains("desktop")));
    assert!(ch.stat.as_deref().unwrap_or("").contains("extra.txt"));
    let l = ext::load_ledger(&s.paths()).unwrap();
    assert_eq!(
        l.extensions["net-tool"].commit.as_deref(),
        Some(old.as_str())
    );
    // declined: nothing changes
    assert!(ext::update(&s.paths(), "net-tool", &UpdateOpts::default(), &mut no).is_err());
    let l = ext::load_ledger(&s.paths()).unwrap();
    assert_eq!(
        l.extensions["net-tool"].commit.as_deref(),
        Some(old.as_str())
    );
    assert!(l.txn.is_none());
    // approved: the checkout and the ledger move together
    let mut shown = String::new();
    let r = ext::update(&s.paths(), "net-tool", &UpdateOpts::default(), &mut |p| {
        shown = p.describe();
        Some(Approval::Interactive)
    })
    .unwrap();
    assert_eq!(r.op, "update");
    assert!(shown.contains("NEW PERMISSIONS"), "{shown}");
    assert!(shown.contains("+ extra.txt"), "{shown}");
    let l = ext::load_ledger(&s.paths()).unwrap();
    let e = &l.extensions["net-tool"];
    assert_eq!(e.commit.as_deref(), Some(new.as_str()));
    assert_eq!(e.version, "0.2.0");
    assert!(l.txn.is_none());
    let src = s.paths().ext_dir().join("src/net-tool");
    assert!(src.join("extra.txt").is_file());
    assert_eq!(git(&src, &["rev-parse", "HEAD"]), new);
    // the link's recorded hash is the file's
    let link = &e.parts[0].links[0];
    assert_eq!(link.sha256, ext::sha256_file(&link.link).unwrap());
    // no stage or old copy left behind
    let left: Vec<_> = fs::read_dir(s.paths().ext_dir().join("src"))
        .unwrap()
        .flatten()
        .map(|e| e.file_name())
        .collect();
    assert_eq!(left, vec![std::ffi::OsString::from("net-tool")]);
}

#[test]
fn a_tag_pins_until_moved() {
    let s = Sandbox::new();
    let repo = s.repo(Kind::Theme, "pinned");
    git(&repo, &["tag", "v1.0.0"]);
    let v1 = git(&repo, &["rev-parse", "HEAD"]);
    fs::write(repo.join("NOTES"), "2\n").unwrap();
    commit(&repo, "two");
    git(&repo, &["tag", "v1.1.0"]);
    let r = ext::install(
        &s.paths(),
        &format!("{}@v1.0.0", repo.display()),
        &InstallOpts::default(),
        &mut no,
    )
    .unwrap();
    assert_eq!(r.commit.as_deref(), Some(v1.as_str()));
    let r = ext::update(&s.paths(), "pinned", &UpdateOpts::default(), &mut no).unwrap();
    assert_eq!(r.op, "pinned");
    assert!(r.detail.contains("v1.1.0"), "{}", r.detail);
    let r = ext::update(
        &s.paths(),
        "pinned",
        &UpdateOpts {
            git_ref: Some("v1.1.0".into()),
            ..Default::default()
        },
        &mut no,
    )
    .unwrap();
    assert_eq!(r.op, "update", "a theme moves without a question");
    let l = ext::load_ledger(&s.paths()).unwrap();
    assert_eq!(
        l.extensions["pinned"].source.git_ref.as_deref(),
        Some("v1.1.0")
    );
    assert_eq!(l.extensions["pinned"].source.ref_kind, "tag");
}

#[test]
fn hand_edits_are_seen_and_an_update_restores_them() {
    let s = Sandbox::new();
    let repo = s.repo(Kind::HomelabAdapter, "lab-host");
    install(&s, &repo).unwrap();
    let f = s.paths().ext_dir().join("src/lab-host/adapter.py");
    fs::write(&f, "# changed by hand\n").unwrap();
    let l = ext::list(&s.paths(), true).unwrap();
    assert_eq!(l.extensions[0].status, "modified");
    let r = ext::update(&s.paths(), "lab-host", &UpdateOpts::default(), &mut yes).unwrap();
    assert_eq!(r.op, "update");
    let ch = r.plan.unwrap().changes.unwrap();
    assert!(ch.local_edits.contains(&"adapter.py".to_owned()));
    assert_ne!(fs::read_to_string(&f).unwrap(), "# changed by hand\n");
    assert_eq!(
        ext::list(&s.paths(), true).unwrap().extensions[0].status,
        "ok"
    );
}

#[test]
fn paths_out_of_the_extension_are_refused() {
    let s = Sandbox::new();
    // a part that climbs out
    let repo = s.repo(Kind::Widget, "climber");
    let m = repo.join("bromigos-ext.toml");
    let text = fs::read_to_string(&m).unwrap();
    fs::write(
        &m,
        text.replace("path = \"widget.py\"", "path = \"../climber/widget.py\""),
    )
    .unwrap();
    commit(&repo, "climb");
    let e = install(&s, &repo).unwrap_err();
    assert!(e.0.contains("leaves the extension"), "{e}");
    // a symlink out of the repository
    let repo = s.repo(Kind::Theme, "leaky");
    symlink("/etc/passwd", repo.join("passwd")).unwrap();
    commit(&repo, "leak");
    let e = install(&s, &repo).unwrap_err();
    assert!(e.0.contains("symlink out of the extension"), "{e}");
    // a part that is itself a symlink (even inside)
    let repo = s.repo(Kind::VectorTool, "linked-tool");
    fs::rename(repo.join("tool.py"), repo.join("real.py")).unwrap();
    symlink("real.py", repo.join("tool.py")).unwrap();
    commit(&repo, "link");
    let e = install(&s, &repo).unwrap_err();
    assert!(e.0.contains("can't be a symlink"), "{e}");
    // an absolute path
    let repo = s.repo(Kind::Hook, "abs-hook");
    let m = repo.join("bromigos-ext.toml");
    let text = fs::read_to_string(&m).unwrap();
    fs::write(
        &m,
        text.replace("path = \"theme-set\"", "path = \"/bin/sh\""),
    )
    .unwrap();
    commit(&repo, "abs");
    assert!(install(&s, &repo).is_err());
    // nothing was installed by any of them
    assert!(ext::load_ledger(&s.paths()).unwrap().extensions.is_empty());
    let src = s.paths().ext_dir().join("src");
    assert_eq!(fs::read_dir(&src).map(|d| d.count()).unwrap_or(0), 0);
}

#[test]
fn declared_permissions_must_match_the_parts() {
    let s = Sandbox::new();
    let repo = s.repo(Kind::LiveDeck, "quiet-deck");
    let m = repo.join("bromigos-ext.toml");
    let text = fs::read_to_string(&m).unwrap();
    fs::write(&m, text.replace("code = true", "code = false")).unwrap();
    commit(&repo, "hide the code");
    let e = install(&s, &repo).unwrap_err();
    assert!(e.0.contains("runs code"), "{e}");
    let repo = s.repo(Kind::VectorTool, "root-tool");
    let m = repo.join("bromigos-ext.toml");
    let text = fs::read_to_string(&m).unwrap();
    fs::write(
        &m,
        text.replace("vector = \"read\"", "vector = \"terminal\""),
    )
    .unwrap();
    commit(&repo, "ask for the terminal");
    let e = install(&s, &repo).unwrap_err();
    assert!(e.0.contains("never gets VECTOR's terminal"), "{e}");
    let repo = s.repo(Kind::Theme, "future");
    let m = repo.join("bromigos-ext.toml");
    let text = fs::read_to_string(&m).unwrap();
    fs::write(&m, text.replace(">=1.0, <2", ">=2")).unwrap();
    commit(&repo, "needs 2");
    let e = install(&s, &repo).unwrap_err();
    assert!(e.0.contains("needs bromigOS extension API"), "{e}");
}

#[test]
fn name_clashes_are_refused() {
    let s = Sandbox::new();
    let p = s.paths();
    // the same extension twice
    let repo = s.repo(Kind::LiveDeck, "twice");
    install(&s, &repo).unwrap();
    assert!(
        install(&s, &repo)
            .unwrap_err()
            .0
            .contains("already installed")
    );
    // another extension with a part of the same name
    let other = s.path("repos/other");
    ext::new_starter(Kind::LiveDeck, "other", &other).unwrap();
    let m = other.join("bromigos-ext.toml");
    let text = fs::read_to_string(&m).unwrap();
    // the part's name (the line with a comment after it), not the extension's
    fs::write(&m, text.replace("name = \"other\" ", "name = \"twice\" ")).unwrap();
    git(&other, &["init", "-q", "-b", "main"]);
    commit(&other, "clash");
    let e = install(&s, &other).unwrap_err();
    assert!(e.0.contains("clashes with extension twice"), "{e}");
    // a first-party theme's name
    fs::create_dir_all(p.share_dir.join("themes/wick")).unwrap();
    let repo = s.repo(Kind::Theme, "wick");
    let e = install(&s, &repo).unwrap_err();
    assert!(e.0.contains("clashes with"), "{e}");
    // a packaged command's name
    fs::create_dir_all(&p.lib_bin).unwrap();
    fs::write(p.lib_bin.join("bromigos-taken"), "#!/bin/sh\n").unwrap();
    let repo = s.repo(Kind::Command, "taken");
    let e = install(&s, &repo).unwrap_err();
    assert!(e.0.contains("clashes with"), "{e}");
}

#[test]
fn a_theme_of_the_users_is_adopted_only_when_asked() {
    let s = Sandbox::new();
    let p = s.paths();
    let mine = p.user_config_dir().join("themes/teal");
    ext::new_starter(Kind::Theme, "teal", &mine).unwrap();
    fs::remove_file(mine.join("bromigos-ext.toml")).unwrap();
    let repo = s.repo(Kind::Theme, "teal");
    let e = install(&s, &repo).unwrap_err();
    assert!(e.0.contains("--adopt"), "{e}");
    assert_eq!(ext::list(&p, false).unwrap().unmanaged_themes, vec!["teal"]);
    ext::install(
        &p,
        &repo.to_string_lossy(),
        &InstallOpts {
            adopt: true,
            ..Default::default()
        },
        &mut no,
    )
    .unwrap();
    assert!(!mine.exists());
    let kept: Vec<_> = fs::read_dir(p.ext_state_dir().join("adopted"))
        .unwrap()
        .flatten()
        .collect();
    assert_eq!(kept.len(), 1);
    assert!(ext::list(&p, false).unwrap().unmanaged_themes.is_empty());
}

#[test]
fn a_repository_without_a_manifest_installs_as_a_theme() {
    let s = Sandbox::new();
    let repo = s.path("repos/bromigos-theme-dusk");
    ext::new_starter(Kind::Theme, "dusk", &repo).unwrap();
    fs::remove_file(repo.join("bromigos-ext.toml")).unwrap();
    git(&repo, &["init", "-q", "-b", "main"]);
    commit(&repo, "a theme");
    let r = install(&s, &repo).unwrap();
    assert_eq!(r.name, "dusk");
    assert!(s.active("themes/dusk").exists());
}

#[test]
fn a_folder_without_git_is_copied_and_updates_from_it() {
    let s = Sandbox::new();
    let d = s.path("work/plain-skill");
    ext::new_starter(Kind::VectorSkill, "plain-skill", &d).unwrap();
    let r = install(&s, &d).unwrap();
    assert_eq!(r.commit, None);
    let l = ext::load_ledger(&s.paths()).unwrap();
    assert_eq!(l.extensions["plain-skill"].source.kind, "copy");
    fs::write(
        d.join("skill.md"),
        "---\nname: plain-skill\ndescription: d\n---\nnew\n",
    )
    .unwrap();
    let r = ext::update(&s.paths(), "plain-skill", &UpdateOpts::default(), &mut yes).unwrap();
    assert_eq!(r.op, "update");
    assert!(
        fs::read_to_string(s.active("skills/plain-skill.md"))
            .unwrap()
            .contains("new")
    );
}

#[test]
fn the_catalog_is_searched_and_installs_by_name() {
    let s = Sandbox::new();
    let cat = s.path("catalog");
    fs::create_dir_all(cat.join("examples")).unwrap();
    ext::new_starter(
        Kind::LiveDeck,
        "hello-deck",
        &cat.join("examples/hello-deck"),
    )
    .unwrap();
    fs::create_dir_all(cat.join("previews")).unwrap();
    fs::write(cat.join("previews/hello-deck.png"), b"png").unwrap();
    fs::write(
        cat.join("index.toml"),
        format!(
            "schema = 1\n\n[[extension]]\nname = \"hello-deck\"\ndescription = \"A deck\"\n\
             kinds = [\"live-deck\"]\nurl = \"{}\"\npath = \"examples/hello-deck\"\n\
             preview = \"previews/hello-deck.png\"\ntags = [\"example\"]\n\n\
             [[extension]]\nname = \"mire\"\ndescription = \"A bayou\"\nkinds = [\"theme\"]\n\
             url = \"https://github.com/bromigos-org/bromigOS\"\npath = \"themes/mire\"\nbundled = true\n",
            cat.display()
        ),
    )
    .unwrap();
    git(&cat, &["init", "-q", "-b", "main"]);
    commit(&cat, "catalog");
    // SAFETY: tests in this file don't read the variable concurrently
    unsafe { std::env::set_var("BROMIGOS_EXT_CATALOGS", &cat) };
    let p = s.paths();
    let found = ext::search(&p, Some("deck"), None, false).unwrap();
    assert_eq!(found.results.len(), 1);
    let h = &found.results[0];
    assert_eq!(h.install, ["bromigos", "ext", "install", "hello-deck"]);
    assert!(
        h.entry
            .preview
            .as_deref()
            .unwrap()
            .ends_with("previews/hello-deck.png")
    );
    let themes = ext::search(&p, None, Some(Kind::Theme), false).unwrap();
    assert_eq!(themes.results[0].entry.name, "mire");
    assert!(themes.results[0].installed, "bundled: nothing to install");
    let r = ext::install(&p, "hello-deck", &InstallOpts::default(), &mut yes).unwrap();
    assert_eq!(r.name, "hello-deck");
    let l = ext::load_ledger(&p).unwrap();
    assert_eq!(
        l.extensions["hello-deck"].source.path.as_deref(),
        Some("examples/hello-deck")
    );
    assert!(fs::read_link(s.active("live/decks/hello-deck.py")).is_ok());
    assert!(
        ext::install(&p, "mire", &InstallOpts::default(), &mut yes)
            .unwrap_err()
            .0
            .contains("ships with bromigOS")
    );
    unsafe { std::env::remove_var("BROMIGOS_EXT_CATALOGS") };
}

#[test]
fn a_starter_tree_with_executable_bits() {
    let d = tempfile::tempdir().unwrap();
    let c = d.path().join("say-hi");
    ext::new_starter(Kind::Command, "say-hi", &c).unwrap();
    let m = fs::metadata(c.join("bromigos-say-hi")).unwrap();
    assert_ne!(m.permissions().mode() & 0o111, 0);
    assert!(ext::new_starter(Kind::Command, "say_hi", &d.path().join("x")).is_err());
    assert!(
        ext::new_starter(Kind::Theme, "say-hi", &c).is_err(),
        "not into a full folder"
    );
}

#[test]
fn theme_new_from_copies_and_renames() {
    let s = Sandbox::new();
    let p = s.paths();
    let src = p.share_dir.join("themes/ember");
    ext::new_starter(Kind::Theme, "ember", &src).unwrap();
    fs::remove_file(src.join("bromigos-ext.toml")).unwrap();
    fs::create_dir_all(src.join("backgrounds")).unwrap();
    fs::write(src.join("backgrounds/a.png"), b"png").unwrap();
    let out = s.path("work/coal");
    ext::new_theme_from(&p, "coal", "ember", &out).unwrap();
    assert!(out.join("backgrounds/a.png").is_file());
    let tt = fs::read_to_string(out.join("theme.toml")).unwrap();
    assert!(tt.contains("name = \"Coal\""), "{tt}");
    let c = ext::check(&out, None).unwrap();
    assert_eq!(c.manifest.extension.name, "coal");
}

#[test]
fn the_theme_starter_renders_every_template() {
    // the repository is the share dir (its themes and templates), as BROMIGOS_SHARE_DIR=<checkout>
    let d = tempfile::tempdir().unwrap();
    let repo = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..");
    let m: HashMap<&str, PathBuf> = [
        ("HOME", d.path().join("home")),
        ("XDG_RUNTIME_DIR", d.path().join("run")),
        ("BROMIGOS_SHARE_DIR", repo),
    ]
    .into_iter()
    .collect();
    let p = Paths::from_lookup(|k| m.get(k).cloned());
    let src = d.path().join("starter");
    ext::new_starter(Kind::Theme, "starter-teal", &src).unwrap();
    ext::install(&p, &src.to_string_lossy(), &InstallOpts::default(), &mut no).unwrap();
    let r = bromigos_core::theme::set(&p, "starter-teal").unwrap_or_else(|e| panic!("{e}"));
    assert!(r.rendered.len() > 5, "{:?}", r.rendered);
}

#[test]
fn shipped_bytecode_is_refused_and_generated_bytecode_ignored() {
    let s = Sandbox::new();
    let repo = s.repo(Kind::Widget, "pyc-panel");
    fs::create_dir_all(repo.join("__pycache__")).unwrap();
    fs::write(repo.join("__pycache__/widget.cpython-314.pyc"), b"\0").unwrap();
    commit(&repo, "bytecode");
    let e = install(&s, &repo).unwrap_err();
    assert!(e.0.contains("compiled Python"), "{e}");
    git(&repo, &["rm", "-rq", "__pycache__"]);
    commit(&repo, "no bytecode");
    install(&s, &repo).unwrap();
    // Python writes its cache beside the module once it's imported: not a change
    let src = s.paths().ext_dir().join("src/pyc-panel");
    fs::create_dir_all(src.join("__pycache__")).unwrap();
    fs::write(src.join("__pycache__/widget.cpython-314.pyc"), b"\0").unwrap();
    assert_eq!(
        ext::list(&s.paths(), true).unwrap().extensions[0].status,
        "ok"
    );
}
