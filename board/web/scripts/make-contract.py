#!/usr/bin/env python3
"""Writes board/web/tests/contract/service.json: what the board's service really answers, for the
page's contract tests (tests/contract.spec.ts) and its fixtures' shape check (tests/shapes.spec.ts).

Nothing in the file is written by hand. Each part is made by the code that makes it on a server:

  the commands' documents   the libraries behind `bromigos storage health`, `bromigos alerts`,
                            `bromigos lab backups status`, `bromigos activity list`,
                            `bromigos server status`, `bromigos lab apps list` and
                            `bromigos lab apps budget` (each with --json), run on the stand-in
                            machines their own tests use
  the board and the door    the service's snapshot reader (snapshot.gather, with its scrub) and
                            its API (api.make_app), asked over HTTP through Starlette's test client

  python3 board/web/scripts/make-contract.py [--service DIR | --ref REF] [--check | --shapes]

The service is read from this checkout (board/lib/bromigos_board) once it is here, else from a
git ref (default origin/feat/board-service), else from --service DIR. --check writes nothing and
exits 1 when the file on disk differs at all. --shapes writes nothing and exits 1 only when a
shape differs: a key that came or went, or a value of another type (CI runs this: a new app in
the catalogue changes the file but no shape, and needs nothing). Needs python-starlette and
python-httpx, as the service's own tests do. Nothing on this machine is read or changed: every
root is a temporary folder.
"""
import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

os.environ["TZ"] = "UTC"
time.tzset()

REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "board/web/tests/contract/service.json"
NOW = 1794290000000                       # 2026-11-10 05:53:20 UTC, the service's tests' clock
MIN, HOUR, DAY = 60_000, 3_600_000, 86_400_000
S3 = "s3:https://s3.example/backups/myserver"

for p in ("lib", "homelab/lib", "homelab/tests", "tests/alerts", "tests/activity", "server/tests"):
    sys.path.insert(0, str(REPO / p))


def quiet(fn, *a, **kw):
    with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()):
        code = fn(*a, **kw)
    return code, out.getvalue()


# ---------------------------------------------------------------- the commands, on their tests' stand-ins
def drives_and_alerts():
    """`bromigos storage health --json` and `bromigos alerts --json` from one stand-in machine
    (tests/alerts): three healthy drives; then sdb grows reallocated sectors; and a machine with
    one drive on watch and one that gives no health records."""
    import test_drive_health as T
    import bromigos_alerts as A
    import bromigos_drives as D

    def machine(start):
        m = T.FakeMachine(role="server")
        for name, text in T.STUBS.items():
            (m.bin / name).write_text(text)
            (m.bin / name).chmod(0o755)
        for p in (m.fake / "smart").iterdir():
            p.unlink()
        m.now, m.devices = start, {}
        return m

    def plug(m, name, doc):
        m.devices[name] = doc
        m.write(f"smart/{name}.json", doc)
        m.write(f"smart/{name}.json.rc", "0")
        m.write("smart/scan.json", {"devices": [
            {"name": f"/dev/{n}", "info_name": f"/dev/{n}", "type": "nvme" if n.startswith("nvme") else "scsi",
             "protocol": "NVMe" if n.startswith("nvme") else "SCSI"} for n in sorted(m.devices)]})

    def check(m, ms=0):
        m.now += ms
        A.run_pass(m.env(), "system", checks={"disk.smart"})

    def read(m):
        e = m.env()
        r = subprocess.run([sys.executable, str(REPO / "bin/bromigos-alerts"), "--json"], env=dict(e.environ, TZ="UTC"),
                           capture_output=True, text=True)
        return {"storage": strip(D.report(e), m.tmp.name), "alerts": strip(json.loads(r.stdout), m.tmp.name)}

    out = {}
    last = NOW - 12 * MIN                                  # the system pass reads the drives every 15 minutes
    m = machine(last - 40 * DAY)
    plug(m, "nvme0", T.nvme())
    plug(m, "sda", T.sata(serial="FAKE0SATA000002"))
    plug(m, "sdb", T.sata(serial="FAKE0SATA000003"))
    check(m)
    for _ in range(37):
        check(m, DAY)
    check(m, 3 * DAY)
    assert m.now == last
    out["healthy"] = read(m)
    m.close()

    m = machine(last - 40 * DAY)
    plug(m, "nvme0", T.nvme())
    plug(m, "sda", T.sata(serial="FAKE0SATA000002"))
    plug(m, "sdb", T.sata(serial="FAKE0SATA000003"))
    check(m)
    for _ in range(37):
        check(m, DAY)
    plug(m, "sdb", T.sata(serial="FAKE0SATA000003", Reallocated_Sector_Ct=8))
    check(m, 3 * DAY)
    out["worse"] = read(m)
    m.close()

    m = machine(last - 40 * DAY)
    plug(m, "nvme0", T.nvme())
    plug(m, "sda", T.sata(serial="FAKE0SATA000002", Reallocated_Sector_Ct=12))   # old errors that never grow: watch
    plug(m, "sdc", T.fixture("smartctl-usb-bridge.json"))                         # no health records: cannot tell
    check(m)
    for _ in range(39):
        check(m, DAY)
    check(m, DAY)
    out["watch"] = read(m)
    m.close()
    # the healthy machine again, with two channels of its own (`bromigos alerts channels`,
    # lib/bromigos_notify.py): Discord with quiet hours, and a webhook that picks its sources, whose
    # last message didn't go and one of whose settings is wrong. The addresses are stand-ins, kept
    # where the command keeps them; the document only ever says "set".
    import bromigos_notify as N
    m = machine(last - 40 * DAY)
    plug(m, "nvme0", T.nvme())
    plug(m, "sda", T.sata(serial="FAKE0SATA000002"))
    plug(m, "sdb", T.sata(serial="FAKE0SATA000003"))
    check(m)
    for _ in range(37):
        check(m, DAY)
    check(m, 3 * DAY)
    m.rootfile(A.SETTINGS, '[notify]\nboard = "https://myserver.local"\n\n'
               '[channels.discord]\ntype = "discord"\nquiet = "22:00-07:00"\ncritical_in_quiet = true\n\n'
               '[channels.ops]\ntype = "webhook"\nseverities = ["critical"]\nsources = ["drives", "backups", "job-results"]\n'
               'resolved = true\nquiet = "late"\n\n'
               '[channels.spare]\ntype = "discord"\non = false\n')
    e = m.env()
    N.write_secret(e, "discord", "url", "https://discord.com/api/webhooks/1/stand-in")
    N.write_secret(e, "ops", "url", "https://hooks.example/alerts")
    N.write_secret(e, "ops", "key", "stand-in")
    st = {}
    N._worked(st, last - 2 * DAY)
    N.save_state(e, "discord", st)
    st = {}
    N._worked(st, last - 9 * DAY)
    N._failed(st, last - 3 * HOUR, "the channel answered 404 (the address is gone)")
    N.save_state(e, "ops", st)
    out["channels"] = read(m)
    m.close()
    names = [c["name"] for c in out["channels"]["alerts"]["channels"]["channels"]]
    assert names == ["discord", "ops", "spare", "brodec"], names

    for k, want in (("healthy", {"healthy"}), ("worse", {"healthy", "worse"}), ("watch", {"healthy", "watch", "unknown"})):
        got = {d["verdict"] for d in out[k]["storage"]["drives"]}
        assert got == want, (k, got)
    return out


def backups():
    """`bromigos lab backups status --json` (lib/bromigos_backups.status_doc) from a stand-in root's
    server.toml and backup.json: healthy with a proven restore, one that needs a look (the last run
    failed), off, and a computer that isn't a server (its error document)."""
    import bromigos_backups as B
    now = NOW / 1000

    def doc(config, state):
        with tempfile.TemporaryDirectory() as t:
            with mock.patch.object(B, "ROOT", t):
                if config is not None:
                    p = Path(B.at(B.CONFIG))
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(config)
                if state is not None:
                    B.write_json(B.STATE, state)
                return strip(B.status_doc(now), t)

    def rec(phase, age_h, **more):
        ts = now - age_h * 3600
        return dict({"phase": phase, "at": B.iso(ts), "ts": ts}, **more)

    on = f'[backup]\nto = "{S3}"\n'
    good = {"run": rec("ok", 7), "run_ok": rec("ok", 7), "check": rec("ok", 30), "check_ok": rec("ok", 30),
            "test": rec("ok", 12 * 24, files=100), "test_ok": rec("ok", 12 * 24, files=100),
            "snapshots": {"count": 17, "oldest": B.iso(now - 180 * 86400), "newest": B.iso(now - 7 * 3600)}}
    bad = dict(good, run=rec("failed", 7, reason="the destination didn't answer"), run_ok=rec("ok", 55))
    # the same, with a backup drive that is carried away (the Go Bag), its last copy four days old
    carried = dict(good, drives={"5c1e-77a0": {"label": "GOBAG", "model": "Extreme 55AE", "size": 1000204886016, "fstype": "ext4",
                                               "added_at": B.iso(now - 11 * 86400), "added_ts": now - 11 * 86400,
                                               "run": rec("ok", 96), "run_ok": rec("ok", 96)}})
    out = {"healthy": doc(on, good), "attention": doc(on, bad), "gobag": doc(on, carried), "off": doc("[backup]\n", {}),
           "not_a_server": doc(None, None)}
    assert out["gobag"]["drives"] and out["gobag"]["drives"][0]["last_good_copy"]["ts"] == now - 96 * 3600, out["gobag"]["drives"]
    assert out["healthy"]["health"]["state"] == "ok" and out["attention"]["health"]["state"] == "attention", out
    assert out["off"]["health"]["state"] == "off" and out["not_a_server"]["server"] is False
    return out


def system():
    """`bromigos server status --json` from the stand-in root server/tests uses, after an update
    that came back healthy."""
    import test_server as T
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        root, fake, bin_ = t / "root", t / "fake", t / "bin"
        for d in (root / "etc/bromigos", fake, bin_, root / "var/lib/bromigos/server"):
            d.mkdir(parents=True)
        for name, text in T.STUBS.items():
            (bin_ / name).write_text(text)
            (bin_ / name).chmod(0o755)
        (root / "etc/bromigos/server.toml").write_text(f'[health]\nminutes = 0\n[updates]\nwindow = "03:00-05:00"\n[backup]\nto = "{S3}"\n')
        done = NOW / 1000 - 10 * 3600
        # as bromigos-server's now() writes a time
        iso = lambda ts: __import__("datetime").datetime.fromtimestamp(ts, __import__("datetime").timezone.utc).isoformat(timespec="seconds")
        (root / "var/lib/bromigos/server/update.json").write_text(json.dumps({
            "phase": "ok", "started": iso(done - 400), "finished": iso(done), "finished_ts": done,
            "last_success_ts": done, "pre": 40, "post": 41, "packages": ["bash", "linux-lts"], "reason": "", "kernel": True}))
        env = dict(os.environ, PATH=f"{bin_}:/usr/bin:/bin", FAKE=str(fake), BROMIGOS_SERVER_ROOT=str(root),
                   BROMIGOS_SERVER_SHARE=str(T.HERE), BROMIGOS_SERVER_HEALTH_POLL="0", TZ="UTC",
                   BROMIGOS_SERVER_NEWS_FEED="file:///nonexistent/arch-news.xml")
        r = subprocess.run([sys.executable, "-I", str(T.SCRIPT), "status", "--json"], env=env, capture_output=True, text=True)
        doc = strip(json.loads(r.stdout), tmp)
    # this machine's own name and kernel are not the stand-in's: the example server's instead
    doc["hostname"] = "myserver"
    doc["kernel"]["running"] = "6.12.59-1-lts"
    return doc


def apps():
    """`bromigos lab apps list --json` from the stand-in machine homelab/tests uses: Caddy, Photos
    and Passwords installed and running; the same with Photos' services down; nothing installed;
    and the running one on a box whose scan finds a graphics card (an NVIDIA one, 12 GB).
    And `bromigos lab apps budget --json` from each (under "<name>.budget"): the service reads
    what is in the box from it."""
    import test_lab_apps as T
    from bromigos_homelab import labapps as A, provcatalog as PC
    out = {}
    with mock.patch.object(PC, "SHARE", "/nonexistent"):
        PC._cache.clear()
        for name in ("running", "down", "none", "gpu"):
            case = T.Tiles("server")
            case.setUp()
            try:
                if name == "gpu":   # the scan's own keys: the card's kind in `gpu`, its memory in `gpu_vram_gb`
                    case.m = case.machine(hw=dict(T.HW, gpu="nvidia", gpu_vram_gb=12))
                if name != "none":
                    case.server()
                if name == "down":
                    case.fm.active -= set(T.PHOTOS_UNITS)
                code, text = quiet(A.main, ["list", "--json"], ["/usr/lib/bromigos/bin/bromigos-lab", "apps"], case.m)
                out[name] = strip(json.loads(text), case.root)
                code, text = quiet(A.main, ["budget", "--json"], ["/usr/lib/bromigos/bin/bromigos-lab", "apps"], case.m)
                out[f"{name}.budget"] = strip(json.loads(text), case.root)
            finally:
                case.doCleanups()
        PC._cache.clear()
    by = {t["id"]: t for t in out["running"]}
    assert by["photos"]["state"] == "ok" and {t["id"]: t for t in out["down"]}["photos"]["state"] == "down"
    assert not any(t["installed"] for t in out["none"])
    assert out["running.budget"]["hardware"]["cpu"] == T.HW["cpu"] and out["none.budget"]["installed"]["ids"] == []
    assert out["gpu.budget"]["hardware"]["gpu"] == "nvidia", out["gpu.budget"]["hardware"]
    return out


def activity(root, which):
    """Jobs written by the activity library itself into the service's stand-in root: a backup that
    finished, an update that rolled back, a drive replacement that asks, a backup running now; and
    for the page's job controls, a disk that asks with a choice that can't be undone (`[wipe!]`)
    and a backup that failed and may be started again."""
    import bromigos_activity as A

    class Clock(A.Env):
        t = NOW

        def now_ms(self):
            return Clock.t

    env = Clock(dict(os.environ, BROMIGOS_ROOT=str(root)))

    def job(at, kind, title, subject, lines, end=None, via="timer", **kw):
        Clock.t = at
        j = A.Job(env, kind, title, subject=A.parse_subject(subject), command=["bromigos", *kind.split(".")], via=via, **kw)
        j.open()
        j.begin()
        for step_ms, line in lines:
            Clock.t += step_ms
            j.feed(line)
        if end is not None:
            Clock.t += MIN
            j.finish(**end)
        j.save(force=True)
        return j

    made = []
    if "done" in which:
        made.append(job(NOW - 7 * HOUR - 6 * MIN, "backup.run", "Backing up this server", "backup:myserver:this server", [
            (0, "::step snapshot running Taking a snapshot"), (MIN, "::step snapshot done"),
            (0, "::step copy running Copying what changed"), (4 * MIN, "::step copy done"),
            (0, "::step check running Checking the copy")], end={"exit_code": 0, "words": "Backed up: the copy checks out."}))
    if "rolled-back" in which:
        made.append(job(NOW - 16 * HOUR, "app.update", "Updating Photos", "app:photos:Photos", [
            (0, "::step snapshot running Keeping a way back"), (MIN, "::step snapshot done"),
            (0, "::step install running Installing the new version"), (MIN, "::step install done"),
            (0, "::step check running Checking that it answers"), (2 * MIN, "::error check no answer in 2 minutes")],
            end={"exit_code": 1, "state": "rolled-back"}))
    if "asks" in which:
        made.append(job(NOW - 22 * MIN, "drive.replace", "Replacing a drive: sdb", "drive:sdb:sdb", [
            (0, "::step backup running Backing up first"), (12 * MIN, "::step backup done"),
            (0, "::step out running Taking sdb out of use"), (MIN, "::step out done"),
            (0, "::step swap running Swapping the drive"),
            (0, "::ask swapped Swap the drive now. It is safe to pull sdb. [swapped] I've swapped it [undo] Put sdb back in use")],
            via="board"))
    if "running" in which:
        made.append(job(NOW - 3 * MIN, "backup.run", "Backing up this server", "backup:myserver:this server", [
            (0, "::cancel safe"), (0, "::step snapshot running Taking a snapshot"), (MIN, "::step snapshot done"),
            (0, "::step copy running Copying what changed"), (MIN, "::stage 40 Copying what changed")], via="board"))
    if "asks-danger" in which:
        made.append(job(NOW - 8 * MIN, "storage.add", "Adding a disk: sdc", "drive:sdc:sdc", [
            (0, "::step look running Looking at sdc"), (MIN, "::step look done"),
            (0, "::step use running Making sdc ready"),
            (0, "::ask wipe sdc has a partition with files on it. [wipe!] Wipe sdc and use it [keep] Leave sdc as it is")],
            via="board"))
    if "failed-retry" in which:
        argv = ["bromigos", "backup", "run"]
        made.append(job(NOW - 2 * HOUR, "backup.run", "Backing up this server", "backup:myserver:this server", [
            (0, "::step snapshot running Taking a snapshot"), (MIN, "::step snapshot done"),
            (0, "::step copy running Copying what changed"), (MIN, "::error copy the destination didn't answer")],
            end={"exit_code": 1}, retry=A.retry_spec(argv, "/")))
    Clock.t = NOW
    env2 = dict(os.environ, BROMIGOS_ROOT=str(root), PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, str(REPO / "bin/bromigos-activity"), "list", "--server", "--json"], env=env2,
                       capture_output=True, text=True)
    doc = json.loads(r.stdout)
    return doc, made


def strip(doc, root):
    """A document with the stand-in root taken off every path: what a real server would print."""
    text = json.dumps(doc)
    for r in {str(root), os.path.realpath(str(root))}:
        text = text.replace(r.rstrip("/"), "")
    return json.loads(text)


def two_levels(doc):
    """JSON with a line for each answer and each board, so the file stays small and a change to
    one of them is one line of a diff."""
    c = lambda v: json.dumps(v, sort_keys=True, separators=(",", ":"))
    lines = ["{"]
    keys = sorted(doc)
    for i, k in enumerate(keys):
        v, end = doc[k], "" if i == len(keys) - 1 else ","
        if isinstance(v, dict):
            lines.append(f" {json.dumps(k)}: {{")
            inner = sorted(v)
            lines += [f"  {json.dumps(n)}: {c(v[n])}{'' if j == len(inner) - 1 else ','}" for j, n in enumerate(inner)]
            lines.append(f" }}{end}")
        else:
            lines.append(f" {json.dumps(k)}: {c(v)}{end}")
    return "\n".join(lines + ["}"]) + "\n"


def moved(doc, shift):
    """A recorded ComfyUI answer with its times moved by `shift` ms (its prompts' create_time and
    its messages' timestamps), so they sit just before the samples' NOW."""
    if isinstance(doc, dict):
        return {k: (v + shift if k in ("timestamp", "create_time") and isinstance(v, int) else moved(v, shift)) for k, v in doc.items()}
    if isinstance(doc, list):
        return [moved(v, shift) for v in doc]
    return doc


def lab_case(root, c):
    """The lab's jobs, as the API passes them on (docs/board.md, "The lab's jobs"): the real lab
    follower (bromigos_labjobs.Follower), fed a real ComfyUI's recorded queue, history and websocket
    (tests/activity/fixtures/comfyui) by the activity tests' stand-in, and a job feed's run with a
    thumbnail. Its times are moved so the newest prompt ended 30 seconds before NOW."""
    import bromigos_activity as A
    import bromigos_labjobs as L
    # (tests/alerts has a `fake` too, imported first: the activity tests' own is put in its place)
    other = sys.modules.pop("fake", None)
    try:
        import test_labjobs as T
    finally:
        sys.modules.pop("fake", None)
        if other is not None:
            sys.modules["fake"] = other
    shift = NOW - T.NOW
    queue, history, frames = moved(T.QUEUE, shift), moved(T.HISTORY, shift), moved(T.WS["frames"], shift)
    (root / "etc/bromigos/labjobs.toml").write_text('[[comfyui]]\nname = "studio"\nurl = "http://127.0.0.1:8188"\n')
    os.environ["BROMIGOS_ACTIVITY_NOW_MS"] = str(NOW)
    every, L.PREVIEW_EVERY_S = L.PREVIEW_EVERY_S, 0.0
    out = {}
    try:
        env = A.Env()
        feed = root / "var/lib/bromigos/activity/feed"
        (feed / "ships").mkdir(parents=True, exist_ok=True)
        (feed / "ships" / "cut.png").write_bytes(T.PNG)
        f = L.Feed("ships-20261110", "Universe assets: ships", folder=str(feed), env=env, pid=None)
        f.step("cutout", "Cut out ship-a")
        f.media(str(feed / "ships" / "cut.png"))
        f.step("shape", "Shape ship-a")
        fol = L.Follower(L.Where(env, system=True), websocket=False, http={"studio": T.FakeHttp(queue, history)}, log=lambda w: None)
        fol.graphs[("studio", T.RUNNING)] = queue["queue_running"][0][2]
        for fr in frames:
            fol.on_message({"name": "studio"}, json.dumps(fr["text"]) if "text" in fr else __import__("base64").b64decode(fr["binary"]))
        doc = fol.pass_once()
        with c.stream("GET", "/api/activity") as s:
            out["activity_lab"] = {"request": "GET /api/activity", "status": s.status_code,
                                   "headers": {"content-type": s.headers["content-type"]}, "body": "".join(s.iter_text())}
        out["lab"] = exchange(c.get("/api/lab"))
        name = next(r for r in doc if r["state"] == "succeeded")["result"]["outputs"][0]["media"]
        r = c.get(f"/api/lab/media/{name}")
        out["lab_media"] = {"request": f"GET /api/lab/media/{name}", "status": r.status_code, "body": f"<{len(r.content)} bytes>",
                            "headers": {k: v for k, v in r.headers.items() if k.lower() in (
                                "content-type", "cache-control", "content-security-policy", "x-content-type-options")}}
        out["lab_media_unknown"] = exchange(c.get("/api/lab/media/of-0000000000000000.png"))
    finally:
        os.environ.pop("BROMIGOS_ACTIVITY_NOW_MS", None)
        L.PREVIEW_EVERY_S = every
        (root / "etc/bromigos/labjobs.toml").unlink()
    return out


# ---------------------------------------------------------------- the service
def service_lib(args, stack):
    here = REPO / "board/lib/bromigos_board"
    if args.service:
        base, said = Path(args.service), f"the folder {args.service}"
    elif here.is_dir() and not args.ref:
        base, said = REPO, "this checkout"
    else:
        ref = args.ref or "origin/feat/board-service"
        tmp = stack.enter_context(tempfile.TemporaryDirectory())
        tar = subprocess.run(["git", "-C", str(REPO), "archive", ref, "board/lib", "board/tests"], capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", tmp], input=tar.stdout, check=True)
        commit = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", ref], capture_output=True, text=True).stdout.strip()
        base, said = Path(tmp), f"{ref} ({commit})"
    sys.path.insert(0, str(base / "board/lib"))
    return base, said


def exchange(r, body=None):
    """One answer as the page gets it: its status, the headers the page reads, its body."""
    keep = {k: v for k, v in r.headers.items() if k.lower() in ("content-type", "retry-after", "cache-control")}
    try:
        got = r.json()
    except ValueError:
        got = r.text
    out = {"request": f"{r.request.method} {r.request.url.path}", "status": r.status_code, "headers": keep, "body": got}
    if body is not None:
        out["sent"] = body
    return out


def build(args):
    with contextlib.ExitStack() as stack:
        base, said = service_lib(args, stack)
        from starlette.testclient import TestClient
        from bromigos_board import api, auth, snapshot
        sys.path.insert(0, str(base / "board/tests"))
        from common import LAN as home_address          # a browser on the home network, as the service's tests name one

        cmds = {"drives": drives_and_alerts(), "backups": backups(), "system": system(), "apps": apps()}
        root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        fix = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        stand_in = base / "board/tests/fixtures/bromigos"           # the service's own stand-in `bromigos`
        shutil.copy(stand_in, fix / "bromigos")
        # (the requests folder: on a server with the board's actions set up, `actions` lists them)
        for d in ("run/bromigos-board", "run/bromigos-board/requests", "var/lib/bromigos-board/sessions",
                  "var/lib/bromigos-board/codes", "etc/bromigos"):
            (root / d).mkdir(parents=True, exist_ok=True)
        stack.enter_context(mock.patch.dict(os.environ, {
            "BROMIGOS_ROOT": str(root), "BROMIGOS_BOARD_HOSTNAME": "myserver", "BOARD_FIXTURES": str(fix), "BOARD_MISSING": "",
            "PATH": f"{fix}:{os.environ.get('PATH', '/usr/bin:/bin')}", "BROMIGOS_BOARD_NOW_MS": str(NOW - 5000)}))
        origin = "https://myserver.local"
        page = {"x-bromigos-board": "1", "origin": origin}
        # root's helper, which a server's systemd starts when a request appears: here it is called
        # as each request is written. It is the real one; only the command it would run is not there.
        from bromigos_board import actions

        def helper(rid):
            actions.act(rid, log=lambda words: None, run=lambda argv: subprocess.CompletedProcess(argv, 1, "", "no such command here"))

        app = api.make_app(tries=auth.Tries(), poll=0.05, stream_s=0.4, after_ask=helper, action_wait_s=2)
        c = TestClient(app, base_url=origin, headers={"x-forwarded-for": home_address, "user-agent": "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"})

        def snap(drives="healthy", backups_="healthy", apps_="running", jobs=("done",), missing=(), replace=None, at=NOW - 5000):
            """Write the commands' outputs where the stand-in `bromigos` reads them, and take a snapshot."""
            jobs_dir = root / "var/lib/bromigos/activity"
            shutil.rmtree(jobs_dir, ignore_errors=True)
            act, _ = activity(root, jobs)
            parts = {"storage-health.json": cmds["drives"][drives]["storage"], "alerts.json": cmds["drives"][drives]["alerts"],
                     "backups-status.json": cmds["backups"][backups_], "apps-list.json": cmds["apps"][apps_],
                     "apps-budget.json": cmds["apps"][f"{apps_}.budget"],
                     "server-status.json": cmds["system"], "activity-list.json": strip(act, root)}
            parts.update(replace or {})
            # a server without `bromigos lab apps` has neither its list nor its budget
            gone = set(missing) | ({"apps-budget.json"} if "apps-list.json" in missing else set())
            for name, doc in parts.items():
                # a command that isn't there prints no JSON: the snapshot notes why and its part is null
                (fix / name).write_text("bromigos: no such command\n" if name in gone else json.dumps(doc))
            os.environ["BROMIGOS_BOARD_NOW_MS"] = str(at)
            doc = snapshot.gather()
            snapshot.write(doc)
            os.environ["BROMIGOS_BOARD_NOW_MS"] = str(NOW)
            return doc

        http, boards, doors = {}, {}, {}
        # before anyone signs in
        (root / "run/bromigos-board/board.json").unlink(missing_ok=True)
        doors["no_snapshot"] = c.get("/api/door").json()
        snap()
        http["door"] = exchange(c.get("/api/door"))
        doors["healthy"] = http["door"]["body"]
        http["session_signed_out"] = exchange(c.get("/api/session"))
        http["board_signed_out"] = exchange(c.get("/api/board"))
        http["activity_signed_out"] = exchange(c.get("/api/activity"))
        http["signin_no_header"] = exchange(c.post("/api/session", json={"code": "ABCD-EFGH"}), {"code": "ABCD-EFGH"})
        http["signin_wrong_code"] = exchange(c.post("/api/session", json={"code": "ABCD-EFGH"}, headers=page), {"code": "ABCD-EFGH"})
        code, _ = auth.new_code()
        http["signin"] = exchange(c.post("/api/session", json={"code": code}, headers=page), {"code": "<the code>"})
        assert http["signin"]["status"] == 200, http["signin"]
        http["session_signed_in"] = exchange(c.get("/api/session"))
        http["signout_other_unknown"] = exchange(c.delete("/api/session/0123456789abcdef", headers=page))
        http["no_such_route"] = exchange(c.get("/api/vitals?machine=myserver&range=24h"))
        # a job's own actions (answer, cancel, retry): refused here, where no such job is and nothing is asked of one
        http["job_action_no_job"] = exchange(c.post("/api/activity/20261110-0553-backup.run-myserver-0000/cancel", json={}, headers=page), {})
        http["job_action_unknown"] = exchange(c.post("/api/activity/20261110-0553-backup.run-myserver-0000/undo", json={}, headers=page), {})

        # the board, signed in, in each state the commands can leave it in
        (root / "run/bromigos-board/board.json").unlink()
        http["board_gathering"] = exchange(c.get("/api/board"))
        cases = {
            "healthy": {},
            "needs_you": {"drives": "worse", "jobs": ("done", "rolled-back", "asks")},
            "running": {"jobs": ("done", "running")},
            "drives_watch_unknown": {"drives": "watch"},
            "backups_attention": {"backups_": "attention"},
            "backups_gobag": {"backups_": "gobag"},
            "backups_off": {"backups_": "off"},
            "backups_not_a_server": {"backups_": "not_a_server"},
            "apps_down": {"apps_": "down"},
            "setup": {"apps_": "none", "jobs": ()},
            "apps_missing": {"missing": ("apps-list.json",)},
            "apps_error": {"replace": {"apps-list.json": {"schema": 1, "ok": False, "error": "the catalogue can't be read"}}},
            "storage_missing": {"missing": ("storage-health.json",)},
            "backups_missing": {"missing": ("backups-status.json",)},
            "system_missing": {"missing": ("server-status.json",)},
            "alerts_missing": {"missing": ("alerts.json",)},
            "alerts_channels": {"drives": "channels"},
            "activity_missing": {"missing": ("activity-list.json",)},
            "stale": {"at": NOW - 5 * MIN},
            "hardware_gpu": {"apps_": "gpu"},
            "jobs_controls": {"jobs": ("done", "running", "asks-danger", "failed-retry")},
            "budget_missing": {"missing": ("apps-budget.json",)},
        }
        for name, kw in cases.items():
            snap(**kw)
            r = c.get("/api/board")
            assert r.status_code == 200, (name, r.text)
            boards[name] = r.json()
            if name in ("healthy", "needs_you", "running", "setup"):
                with c.stream("GET", "/api/activity") as s:
                    http[f"activity_{name}"] = {"request": "GET /api/activity", "status": s.status_code,
                                                "headers": {"content-type": s.headers["content-type"]},
                                                "body": "".join(s.iter_text())}
            if name == "apps_missing":
                doors["apps_missing"] = c.get("/api/door").json()
            if name == "jobs_controls":
                # a job's actions on these jobs, through the real API and root's real helper: what
                # each refusal says (the command the helper would run isn't here, so none goes through)
                ids = {(j["kind"], j["state"]): j["id"] for j in boards[name]["activity"]["jobs"]}
                ask, run_ = ids[("storage.add", "needs-you")], ids[("backup.run", "running")]
                done = ids[("backup.run", "succeeded")]
                for key, (job_id, verb, body) in {
                    "job_answer_danger_no_code": (ask, "answer", {"question": "wipe", "choice": "wipe"}),
                    "job_answer_danger_wrong_code": (ask, "answer", {"question": "wipe", "choice": "wipe", "code": "WXYZ-9999"}),
                    "job_answer_bad_choice": (ask, "answer", {"question": "wipe", "choice": "format"}),
                    "job_cancel_not_safe": (ask, "cancel", {}),
                    "job_cancel_ended": (done, "cancel", {}),
                    "job_retry_cant": (run_, "retry", {}),
                }.items():
                    http[key] = exchange(c.post(f"/api/activity/{job_id}/{verb}", json=body, headers=page), body)
        # the lab's jobs: the lab follower's files, the stream, GET /api/lab and a media file
        http.update(lab_case(root, c))
        (root / "etc/bromigos/server.toml").write_text("[board]\ndoor = false\nworld = \"tidewell\"\n")
        snap()
        doors["off"] = c.get("/api/door").json()
        (root / "etc/bromigos/server.toml").unlink()
        http["signout"] = exchange(c.delete("/api/session", headers=page))
        doc = {"about": "What the board's service answers, made by board/web/scripts/make-contract.py from the service's "
                        "own code and the commands' own libraries. Don't edit it: run the script.",
               "service": said.split(" (")[0] if args.ref or not (REPO / "board/lib/bromigos_board").is_dir() else said,
               "now": NOW, "http": http, "boards": boards, "doors": doors}
        text = two_levels(doc)
        text = text.replace(str(root), "").replace(str(fix), "")
        # the browser id and session times are made fresh each run: fixed ones, so the file only changes with the shapes
        ids = sorted(set(re.findall(r'"id": ?"([0-9a-f]{16})"', text)) - {"0123456789abcdef"})
        for n, i in enumerate(ids):
            text = text.replace(i, f"{n + 1:016x}")
        text = re.sub(r'("(?:signed_in_at|last_seen_at|created_at)": ?)\d{13}', rf"\g<1>{NOW}", text)
        text = re.sub(r'("expires_at": ?)\d{13}', rf"\g<1>{NOW + 30 * DAY}", text)
        text = re.sub(r'("request": ?")[0-9a-f]{16}"', r'\g<1>00000000000000a1"', text)      # a request's id is random too
        # a job's id ends in four random characters, and its record carries this machine's boot id
        text = re.sub(r"(\d{8}-\d{4}-[a-z.-]+-[a-z0-9]+-)[0-9a-f]{4}\b",
                      lambda m: m.group(1) + hashlib.sha1(m.group(1).encode()).hexdigest()[:4], text)
        text = re.sub(r'(\\?"boot_id\\?": ?\\?")[0-9a-f-]{36}', r"\g<1>00000000-0000-4000-8000-000000000001", text)
        for private in (socket.gethostname(), os.environ.get("USER", "\0"), "/home/", "/mnt/", "/tmp/"):
            assert private not in text, f"the samples name this machine: {private!r}"
        return text


def learn(s, v):
    """What a value's shape is, added to what was seen at this place: its types, a dict's keys
    (and the ones always there), a list's items."""
    s.setdefault("types", set()).add("null" if v is None else type(v).__name__)
    if isinstance(v, dict):
        s["always"] = set(v) if s.get("always") is None else s["always"] & set(v)
        for k, x in v.items():
            learn(s.setdefault("keys", {}).setdefault(k, {}), x)
    elif isinstance(v, list):
        for x in v:
            learn(s.setdefault("items", {}), x)
    return s


def differences(a, b, path="", out=None):
    """Where two learned shapes differ, as sentences (a: the file on disk, b: the service now)."""
    out = [] if out is None else out
    if a.get("types") != b.get("types"):
        out.append(f"{path or 'the file'}: {' or '.join(sorted(a.get('types', [])))} on disk, {' or '.join(sorted(b.get('types', [])))} now")
    ka, kb = a.get("keys", {}), b.get("keys", {})
    out += [f"{path}.{k}: gone" for k in sorted(set(ka) - set(kb))] + [f"{path}.{k}: new" for k in sorted(set(kb) - set(ka))]
    for k in sorted((a.get("always") or set()) ^ (b.get("always") or set())):
        if k in ka and k in kb:
            out.append(f"{path}.{k}: always there in one, sometimes missing in the other")
    for k in sorted(set(ka) & set(kb)):
        differences(ka[k], kb[k], f"{path}.{k}", out)
    if "items" in a or "items" in b:
        differences(a.get("items", {}), b.get("items", {}), f"{path}[]", out)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--service", help="a folder holding board/lib/bromigos_board and board/tests")
    ap.add_argument("--ref", help="a git ref to read the service from (default: this checkout, else origin/feat/board-service)")
    ap.add_argument("--check", action="store_true", help="write nothing; exit 1 when the file on disk differs")
    ap.add_argument("--shapes", action="store_true", help="write nothing; exit 1 when a shape differs (a key, a type)")
    args = ap.parse_args()
    text = build(args)
    if args.shapes:
        diffs = differences(learn({}, json.loads(OUT.read_text())), learn({}, json.loads(text)))
        for d in diffs[:40]:
            print(d)
        print(f"{len(diffs)} shapes differ: run board/web/scripts/make-contract.py, and see what the page reads of them "
              "(board/web/lib/api/read.ts)" if diffs else "the service's shapes are the ones the page's tests hold")
        return 1 if diffs else 0
    if args.check:
        same = OUT.exists() and OUT.read_text() == text
        print("the contract samples are current" if same else f"{OUT} is stale: run board/web/scripts/make-contract.py")
        return 0 if same else 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text)
    print(f"wrote {OUT} ({len(text) // 1024} KiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
