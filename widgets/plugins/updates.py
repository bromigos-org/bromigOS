"""UPDATES: what `bromigos update` would do, and a button to do it.

Reads `bromigos update --check --json` (core/README.md): the repositories' upgrades, the
AUR's, migrations waiting, what needs a restart or a reboot, the channel, and the last
update's snapshot pair. Checking syncs a throwaway copy of the package databases
(checkupdates), so it runs sparingly: once every 3 hours while the panel is on screen,
when pacman's database changes (an update ran), or when you click CHECK. The answer is
kept in ~/.cache/bromigos/widgets/updates.json, so a restart doesn't check again.
UPDATE runs `bromigos update` in your terminal.
"""
import json
import os
import re
import subprocess
import sys
import time

sys.path.append(os.path.dirname(os.path.realpath(__file__)))   # after the standard library
import _kit as K  # noqa: E402

import draw as D  # noqa: E402

EVERY = 3 * 3600                         # seconds between checks while seen
PACMAN_DB = "/var/lib/pacman/local"      # its mtime moves when packages change
CACHE_FILE = os.path.join(K.CACHE, "updates.json")


# ------------------------------------------------------------------ the data
def _pkg(p):
    """{name, from, to} from {"name", "from", "to"} or "name old -> new"."""
    if isinstance(p, dict):
        return {"name": str(p.get("name") or "?"), "from": p.get("from") or p.get("old"),
                "to": p.get("to") or p.get("new") or p.get("version")}
    m = re.match(r"\s*(\S+)\s+(\S+)\s*->\s*(\S+)", str(p))
    if m:
        return {"name": m.group(1), "from": m.group(2), "to": m.group(3)}
    return {"name": str(p).strip(), "from": None, "to": None}


def parse(doc):
    """The check's answer, in the panel's words:
    {packages: [pkg] | None, aur: [pkg], aur_enabled, aur_note, migrations: [id], restarts:
     [{what, need, why}], reboot: bool, relogin: bool, channel, rollbacks: [{at, pre, post,
     packages: [pkg]}], snapper: bool, snap_pac: bool, boot}"""
    c = (doc or {}).get("check") or {}
    pk = c.get("packages")
    aur = c.get("aur") or {}
    restarts = [{"what": str(r.get("what") or "?"), "need": str(r.get("need") or "restart"),
                 "why": str(r.get("why") or "")} for r in c.get("restarts") or [] if isinstance(r, dict)]
    rb = []
    for r in c.get("rollbacks") or []:
        if not isinstance(r, dict) or r.get("rolled_back"):
            continue
        snap = r.get("snapshot") or {}
        rb.append({"at": K.iso_time(r.get("at")), "pre": snap.get("pre"), "post": snap.get("post"),
                   "channel": r.get("channel"), "packages": [_pkg(p) for p in r.get("packages") or []]})
    snaps = c.get("snapshots") or {}
    return {"packages": None if pk is None else [_pkg(p) for p in pk],
            "aur": [_pkg(p) for p in aur.get("packages") or []], "aur_enabled": bool(aur.get("enabled")),
            "aur_note": aur.get("note"), "migrations": [str(m) for m in c.get("migrations") or []],
            "restarts": restarts, "reboot": any(r["need"] == "reboot" for r in restarts),
            "relogin": any(r["need"] == "relogin" for r in restarts), "channel": c.get("channel"),
            "rollbacks": rb, "snapper": bool(snaps.get("snapper") and snaps.get("config")),
            "snap_pac": bool(snaps.get("snap_pac")), "boot": c.get("boot")}


def pending(d):
    return len(d.get("packages") or []) + len(d.get("aur") or [])


def check(force=False, now=None):
    """The cached answer when it's younger than EVERY (and pacman's database hasn't moved
    since), else a fresh `bromigos update --check --json`. Returns (parsed, checked at)."""
    now = now or time.time()
    try:
        with open(CACHE_FILE) as f:
            cached = json.load(f)
        db = _db_mtime()
        if not force and now - cached["at"] < EVERY and (db is None or db <= cached["at"]):
            return parse(cached["doc"]), cached["at"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        r = subprocess.run(["bromigos", "update", "--check", "--json"], capture_output=True, text=True, timeout=180)
    except FileNotFoundError:
        raise RuntimeError("the bromigos command isn't installed")
    except subprocess.TimeoutExpired:
        raise RuntimeError("the check took over 3 minutes")
    try:
        doc = json.loads(r.stdout)
    except ValueError:
        raise RuntimeError((r.stderr.strip().splitlines() or [f"bromigos update --check said nothing (exit {r.returncode})"])[-1][:160])
    at = time.time()
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        tmp = CACHE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"at": at, "doc": doc}, f)
        os.replace(tmp, CACHE_FILE)
    except OSError:
        pass
    return parse(doc), at


def _db_mtime():
    try:
        return os.path.getmtime(PACMAN_DB)
    except OSError:
        return None


# ------------------------------------------------------------------ demo readings
DEMO_DOC = {"schema": 1, "check": {
    "packages": [{"name": "mesa", "from": "1:25.2.3-1", "to": "1:25.2.4-1"},
                 {"name": "linux", "from": "6.17.1.arch1-1", "to": "6.17.2.arch1-1"},
                 {"name": "firefox", "from": "143.0.3-1", "to": "143.0.4-1"},
                 {"name": "python-cairo", "from": "1.28.0-2", "to": "1.28.0-3"},
                 {"name": "waybar", "from": "0.14.0-3", "to": "0.14.0-4"},
                 {"name": "pipewire", "from": "1:1.4.8-1", "to": "1:1.4.9-1"},
                 {"name": "harfbuzz", "from": "11.5.1-1", "to": "12.0.0-1"},
                 {"name": "bromigos-desktop", "from": "0.1.2.r110-1", "to": "0.1.2.r114-1"},
                 {"name": "sqlite", "from": "3.50.4-2", "to": "3.50.4-3"}],
    "aur": {"enabled": True, "note": None, "packages": [{"name": "visual-studio-code-bin", "from": "1.104.2-1",
                                                         "to": "1.104.3-1"},
                                                        {"name": "zen-browser-bin", "from": "1.16.1b-1", "to": "1.16.2b-1"}]},
    "migrations": ["20261008120200-desktop-user-configs"],
    "restarts": [{"what": "kernel", "need": "reboot", "why": "the running kernel's modules were replaced by a newer kernel",
                  "pids": []},
                 {"what": "dunst", "need": "reload", "why": "its default config is newer", "pids": [1392]}],
    "channel": "stable", "boot": "GRUB: wick (the package's), up to date",
    "snapshots": {"snapper": True, "config": True, "snap_pac": True, "btrfs": True},
    "rollbacks": [{"at": "2026-10-08T21:35:24-07:00", "channel": "stable", "rolled_back": False,
                   "snapshot": {"pre": 216, "post": 217},
                   "packages": ["bromigos-core 0.1.2.r144-1 -> 0.1.2.r145-1", "mesa 1:25.2.2-1 -> 1:25.2.3-1",
                                "openssl 3.5.3-1 -> 3.5.4-1"]},
                  {"at": "2026-10-05T09:12:03-07:00", "channel": "stable", "rolled_back": False,
                   "snapshot": {"pre": 210, "post": 211},
                   "packages": ["linux 6.17.0.arch1-1 -> 6.17.1.arch1-1", "systemd 258-1 -> 258.1-1"]},
                  {"at": "2026-10-01T18:40:51-07:00", "channel": "stable", "rolled_back": False,
                   "snapshot": {"pre": 204, "post": 205}, "packages": ["firefox 143.0.1-1 -> 143.0.3-1"]}]}}


# ------------------------------------------------------------------ the panel
class UpdatesPanel(K.KitPanel):
    name, title = "updates", "UPDATES"
    description = "Updates waiting from the repositories and the AUR, the last update's snapshot, and a button to update"
    category, reads = "system", "bromigos update --check, every 3 hours while shown"
    width, height = 460, 280
    interval = 30.0
    sizes = {
        "compact": ((240, 120), (380, 190), (280, 140)),
        "standard": ((400, 240), (620, 380), (460, 280)),
        "wide": ((640, 200), (1100, 360), (780, 240)),
        "tall": ((380, 420), (560, 900), (420, 560)),
        "large": ((660, 480), (1200, 900), (780, 580)),
    }
    default_size = "standard"
    settings = []

    def __init__(self, cfg=None, wake=None):
        super().__init__(cfg, wake)
        self.force = False
        self.db_seen = _db_mtime()
        if K.demo():
            self.poll = None
            self.data, self.at, self.error = parse(DEMO_DOC), time.time() - 47 * 60, None
        else:
            self.poll = self.poller(self._fetch, every=EVERY, idle=120, name="check")

    def _fetch(self):
        force, self.force = self.force, False
        return check(force)

    def check_now(self):
        if self.poll and not self.poll.busy:
            self.force = True
            self.poll.kick()

    def update(self):
        K.terminal(["bromigos", "update"], title="bromigOS update")

    def tick(self):
        if not self.poll:
            return
        db = _db_mtime()
        if db and self.db_seen and db > self.db_seen and time.monotonic() - self.drawn_at < 120:
            self.db_seen = db                    # packages changed (an update ran): check again
            self.poll.kick()
        elif db:
            self.db_seen = self.db_seen or db

    # ---- the state
    def state(self):
        if self.poll is None:
            return self.data, self.at, self.error, False
        got = self.poll.data
        d, at = got if got else (None, 0)
        return d, at, self.poll.error, self.poll.busy

    def draw(self, cr, w, h):
        cls = self.size_class(w, h)
        d, at, err, busy = self.state()
        right = None
        if d and d.get("channel") and cls != "compact":
            right = f"{d['channel'].upper()} CHANNEL"
        top = D.frame(cr, w, h, self.title, right)
        self.region(0, 0, w, 34, "What `bromigos update` would do: upgrades from the repositories and the AUR, "
                    "migrations, restarts. Checked every 3 hours while this panel is on screen, and when "
                    "packages change" + (f"; you follow the {d['channel']} channel" if d and d.get("channel") else ""))
        if d is None:
            if err:
                self.empty(cr, w, h, top, "COULDN'T CHECK", f"{err}. Try `bromigos update --check` in a terminal.",
                           button=("Check again", "Run the check again", self.check_now))
            else:
                self.empty(cr, w, h, top, "CHECKING…", "Asking the package databases what's new. This takes a few "
                           "seconds.", color="static")
            return
        x0, x1 = 16, w - 16
        if cls == "compact":
            self._compact(cr, d, at, busy, x0, x1, top, h)
            return
        if d.get("packages") is None:
            self.empty(cr, w, h, top, "CAN'T TELL WHAT'S WAITING",
                       "checkupdates is missing or failed. Install pacman-contrib, then check again.",
                       button=("Check again", "Run the check again", self.check_now))
            return
        y = self._summary(cr, d, at, busy, x0, x1, top, cls)
        if cls == "standard":
            y = self._restarts(cr, d, x0, x1, y, limit=2)
            self._pkgs(cr, d, x0, x1, y + 4, h - 12, both=True)
        elif cls == "wide":
            mid = x0 + max(300, (x1 - x0) * 0.38)
            # the summary spans the top; under it, restarts and the snapshot left, packages right
            yy = self._restarts(cr, d, x0, mid - 16, y, limit=3)
            self._snapshot(cr, d, x0, mid - 16, yy + 4, h - 12, limit=3)
            self._pkgs(cr, d, mid, x1, y, h - 12, both=True, columns=(x1 - mid) > 560)
        elif cls == "tall":
            y = self._restarts(cr, d, x0, x1, y, limit=4)
            need = 22 + 18 * (len(d["packages"]) + len(d["aur"]))
            snap_top = min(y + 4 + need + 12, h - 12 - 84)
            self._pkgs(cr, d, x0, x1, y + 4, snap_top - 8, both=True)
            self._snapshot(cr, d, x0, x1, snap_top, h - 12, limit=5)
        else:                                                   # large
            y = self._restarts(cr, d, x0, x1, y, limit=4, inline=True)
            need = 22 + 18 * max(len(d["packages"]), len(d["aur"]), 1)
            snap_top = max(y + 140, min(y + 4 + need + 14, h - 12 - 3 * 36 - 22))
            mid = x0 + (x1 - x0) * 0.6
            self._pkgs(cr, d, x0, mid - 16, y + 4, snap_top - 10, both=False, which="repo")
            self._pkgs(cr, d, mid, x1, y + 4, snap_top - 10, both=False, which="aur")
            self._snapshot(cr, d, x0, x1, snap_top, h - 12, limit=5)

    # ---- pieces
    def _buttons(self, cr, d, x1, y, busy, compact=False):
        """UPDATE and CHECK at the right; returns their left edge."""
        n = pending(d)
        cw = self.button(cr, x1 - 64, y, "…" if busy else "Check", "Check for updates now (it syncs a throwaway copy of "
                         "the package databases, a few seconds)" if not busy else "Checking now…",
                         None if busy else self.check_now)
        ux = x1 - 64 - 8
        lab = "Update"
        bw = D.layout(cr, lab.upper(), 10, "semibold", 0.08).get_pixel_size()[0] + 16
        self.button(cr, ux - bw, y, lab, f"Run `bromigos update` in a terminal: {n} upgrade(s)"
                    + (", migrations and restarts" if d.get("migrations") or d.get("restarts") else "")
                    + ". It asks before it changes anything, and snapshots first when snapper is set up.",
                    self.update, on=n > 0)
        return ux - bw - (0 if compact else 8)

    def _compact(self, cr, d, at, busy, x0, x1, top, h):
        n = pending(d) if d.get("packages") is not None else None
        if n is None:
            D.label(cr, x0, top + 4, "CAN'T TELL", "amber")
            self.region(x0, top, x1 - x0, 30, "checkupdates is missing or failed: install pacman-contrib")
        elif n == 0:
            D.label(cr, x0, top + 8, "UP TO DATE", "phosphor", size=13)
            self.region(x0, top, x1 - x0, 34, f"Nothing to update (checked {K.ago(at)} ago)")
        else:
            col = "amber" if d.get("reboot") else "phosphor"
            sh = max(22, min(50, h - top - 52))
            tw = D.seg7(cr, x0, top + 2, sh, str(n), col)
            D.label(cr, x0 + tw + 10, top + sh - 12, "UPDATES", "dim", size=10)
            self.region(x0, top, tw + 90, sh + 6, f"{len(d['packages'])} from the repositories and {len(d['aur'])} "
                        f"from the AUR waiting (checked {K.ago(at)} ago)")
            if h - top - sh > 64:                   # room: the split under the number
                D.label(cr, x0, top + sh + 12, f"{len(d['packages'])} REPO · {len(d['aur'])} AUR"
                        + (f" · {len(d['migrations'])} MIGRATION" if d.get("migrations") else ""), "soft", size=10)
                self.region(x0, top + sh + 10, x1 - x0, 16, "Upgrades from the repositories and from the AUR"
                            + (", and migrations waiting" if d.get("migrations") else ""))
        if d.get("reboot") or d.get("relogin"):
            word = "REBOOT" if d.get("reboot") else "LOG OUT"
            cw = self.chip(cr, x1 - D.layout(cr, word, 9, "semibold", 0.1).get_pixel_size()[0] - 10, top + 2, word,
                           "amber", "Something running is older than what's installed: " + "; ".join(
                               f"{r['what']}: {r['why']}" for r in d["restarts"] if r["need"] in ("reboot", "relogin")))
            del cw
        self._buttons(cr, d, x1, h - 30, busy, compact=True)
        D.label(cr, x0, h - 26, f"{K.ago(at)} AGO", "static", size=10)
        self.region(x0, h - 28, 80, 16, f"Last checked {K.clock(at)} ({K.ago(at)} ago); the next check is within 3 hours")

    def _summary(self, cr, d, at, busy, x0, x1, top, cls):
        """The counts, the buttons and when it was checked. Returns the y under it."""
        n, a = len(d["packages"]), len(d["aur"])
        y = top + 2
        if n + a == 0 and not d.get("migrations") and not d.get("restarts"):
            D.text(cr, x0, y - 2, "UP TO DATE", 18, "phosphor", "bold", spacing=0.1, glow=True)
            self.region(x0, y - 2, 200, 24, f"Nothing waiting from the repositories or the AUR (checked {K.ago(at)} ago)")
        else:
            x = x0
            for num, word, col, tip in ((n, "REPO", "phosphor" if n else "static",
                                         f"{n} upgrade(s) from the repositories (pacman)"),
                                        (a, "AUR", "phosphor" if a else "static",
                                         (f"{a} upgrade(s) from the AUR (built with your AUR helper)" if d.get("aur_enabled")
                                          else "The AUR is off: `bromigos aur on` lets updates build AUR packages")),
                                        (len(d["migrations"]), "MIGRATE", "soft" if d["migrations"] else "static",
                                         "Migrations waiting: one-time changes to your configuration that the update runs"
                                         + (": " + ", ".join(d["migrations"][:3]) if d["migrations"] else ""))):
                tw = D.text(cr, x, y - 4, str(num), 22, col, "bold", glow=num > 0)[0]
                D.label(cr, x + tw + 5, y + 6, word, "dim", size=10)
                lw = D.layout(cr, word, 10, "semibold", 0.18).get_pixel_size()[0]
                self.region(x, y - 4, tw + lw + 8, 26, tip)
                x += tw + lw + 22
        bx = self._buttons(cr, d, x1, y - 2, busy)
        del bx
        y += 30
        bits = [f"CHECKED {K.ago(at)} AGO"]
        if d.get("snapper"):
            bits.append("SNAPSHOTS ON")
        D.label(cr, x0, y, " · ".join(bits), "static", size=10)
        self.region(x0, y - 2, x1 - x0, 16, f"Last checked at {K.clock(at)}. "
                    + ("Each update is snapshotted first (snapper), so `bromigos update --rollback` can undo it."
                       if d.get("snapper") else "Updates aren't snapshotted: `bromigos rollback setup` turns that on "
                       "(btrfs and snapper)."))
        return y + 20

    def _restarts(self, cr, d, x0, x1, y, limit=3, inline=False):
        rs = d.get("restarts") or []
        if not rs:
            return y
        x = x0
        word = {"reboot": "REBOOT", "relogin": "LOG OUT", "restart": "RESTART", "reload": "RELOAD", "start": "START"}
        shown = 0
        for r in sorted(rs, key=lambda r: r["need"] != "reboot")[:limit]:
            lab = f"{word.get(r['need'], r['need'].upper())}: {r['what']}"
            lw = D.layout(cr, lab.upper(), 9, "semibold", 0.1).get_pixel_size()[0] + 10
            if x + lw > x1:
                x = x0
                y += 20
            col = "amber" if r["need"] in ("reboot", "relogin") else "soft"
            x += self.chip(cr, x, y, lab, col, f"{r['what']} needs a {r['need']}: {r['why']}") + 6
            shown += 1
        if len(rs) > shown:
            more = f"+{len(rs) - shown}"
            if x + D.layout(cr, more, 9, "semibold", 0.1).get_pixel_size()[0] + 10 > x1:
                x = x0
                y += 20
            self.chip(cr, x, y, more, "static", "; ".join(f"{r['what']}: {r['need']}" for r in rs[shown:]))
        return y + 22

    def _pkgs(self, cr, d, x0, x1, top, bottom, both=True, which=None, columns=False):
        """The upgrades, name and from → to; both: repo then AUR in one list."""
        rows = []
        if which in (None, "repo"):
            rows += [("repo", p) for p in d.get("packages") or []]
        if which in (None, "aur"):
            rows += [("aur", p) for p in d.get("aur") or []]
        head = {"repo": "FROM THE REPOSITORIES", "aur": "FROM THE AUR"}.get(which, "WAITING")
        D.label(cr, x0, top, head, "dim", size=10)
        D.rule(cr, x0 + D.layout(cr, head, 10, "semibold", 0.18).get_pixel_size()[0] + 10, top + 7, x1, "dim", 0.3)
        y = top + 18
        if not rows:
            msg = ("The AUR is off." if which == "aur" and not d.get("aur_enabled") else "Nothing waiting.")
            D.text(cr, x0, y, msg, 11, "static", "regular")
            self.region(x0, top, x1 - x0, 36, "Turn the AUR on with `bromigos aur on`" if msg.startswith("The AUR")
                        else "No upgrades waiting here")
            return
        row = 18
        ncol = 2 if columns else 1
        cw = (x1 - x0 - (ncol - 1) * 18) / ncol
        per = max(1, int((bottom - y) // row))
        cap = per * ncol
        shown = rows[:cap if len(rows) <= cap else cap - 1]
        for i, (src, p) in enumerate(shown):
            cx = x0 + (i // per) * (cw + 18)
            cy = y + (i % per) * row
            nw = cw * 0.46
            D.text(cr, cx, cy, p["name"], 11, "soft" if src == "repo" else "cyan", "medium", width=nw)
            ver = f"{p['from'] or '?'} → {p['to'] or '?'}" if p.get("to") else ""
            D.text(cr, cx + cw, cy + 1, ver, 10, "static", "regular", align="right", width=cw - nw - 8)
            self.region(cx, cy - 1, cw, row - 1, f"{p['name']}: {p['from'] or '?'} to {p['to'] or '?'}"
                        + (" (AUR)" if src == "aur" else " (repositories)"))
        if len(rows) > len(shown):
            more = len(rows) - len(shown)
            i = len(shown)
            cx = x0 + (i // per) * (cw + 18)
            cy = y + (i % per) * row
            D.label(cr, cx, cy + 1, f"+{more} MORE", "static", size=10)
            self.region(cx, cy - 1, cw, row - 1, f"{more} more: " + ", ".join(p["name"] for _s, p in rows[len(shown):][:20]))

    def _snapshot(self, cr, d, x0, x1, top, bottom, limit=1):
        rbs = d.get("rollbacks") or []
        head = "LAST UPDATE" if limit == 1 else "RECENT UPDATES"
        D.label(cr, x0, top, head, "dim", size=10)
        D.rule(cr, x0 + D.layout(cr, head, 10, "semibold", 0.18).get_pixel_size()[0] + 10, top + 7, x1, "dim", 0.3)
        y = top + 18
        if not rbs:
            msg = "No update recorded yet." if d.get("snapper") else "Updates aren't snapshotted (no snapper)."
            D.text(cr, x0, y, msg, 11, "static", "regular", width=x1 - x0)
            self.region(x0, top, x1 - x0, 36, msg + (" `bromigos rollback setup` turns snapshots on." if not d.get("snapper")
                                                     else ""))
            return
        row = 34 if limit == 1 else 36
        for r in rbs[:max(1, min(limit, int((bottom - y) // row)))]:
            when = time.strftime("%a %d %b %H:%M", time.localtime(r["at"])) if r["at"] else "?"
            D.text(cr, x0, y, when, 11, "soft", "semibold")
            snap = f"SNAPSHOTS {r['pre']}–{r['post']}" if r.get("pre") is not None else "NO SNAPSHOT"
            D.label(cr, x1, y + 1, snap, "phosphor" if r.get("pre") is not None else "static", size=10, align="right")
            names = ", ".join(p["name"] for p in r["packages"])
            D.text(cr, x0, y + 16, f"{len(r['packages'])} package(s): {names}", 10, "static", "regular", width=x1 - x0)
            self.region(x0, y - 1, x1 - x0, row - 2, f"The update on {when}: "
                        + "; ".join(f"{p['name']} {p['from']} to {p['to']}" for p in r["packages"][:12])
                        + (f". Snapshots {r['pre']} (before) and {r['post']} (after): `bromigos update --rollback "
                           f"{r['pre']}` undoes it" if r.get("pre") is not None else ""))
            y += row


PANEL = UpdatesPanel
LAYOUT = {"visible": False}
