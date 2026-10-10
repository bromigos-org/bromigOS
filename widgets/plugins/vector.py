"""VECTOR: the desktop's AI at a glance. What he's doing, his emergency switch, what he did
last, and his pull requests waiting for your review.

  * his state: $XDG_RUNTIME_DIR/bromigos-vector.json, which his daemon rewrites whenever it
    changes (state, mood, voice, model, muted, unread, switch);
  * the emergency switch: `bromigos vector switch toggle`, the same as Super+Ctrl+Esc and
    the bar: off at once, back on only after a YES in a confirmation menu. The panel never
    turns him on by itself;
  * his recent actions: the last lines of his audit log,
    ~/.local/state/bromigos/vector-audit.log. Each shows the tool, whether it went through
    and when. An argument's value never shows whole: only its name, and errors are
    redacted of anything that looks like a token or a key;
  * his open pull requests: `gh search prs --author <his account> --state open` through
    your own `gh` login, every 5 minutes while the panel is on screen. His account is
    `account` in ~/.config/bromigos/widgets/vector.toml (default bromigodev).
"""
import json
import math
import os
import shutil
import subprocess
import sys
import time

sys.path.append(os.path.dirname(os.path.realpath(__file__)))   # after the standard library
import _kit as K  # noqa: E402

import draw as D  # noqa: E402

STATUS = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "bromigos-vector.json")
AUDIT = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "bromigos",
                     "vector-audit.log")
TAIL_BYTES = 96 * 1024
STATES = {"idle": ("IDLE", "phosphor"), "listening": ("LISTENING", "cyan"), "thinking": ("THINKING", "amber"),
          "speaking": ("SPEAKING", "phosphor"), "error": ("ERROR", "danger"), "off": ("NOT RUNNING", "static")}
MOODS = {"calm": "phosphor", "excited": "cyan", "concerned": "amber", "alarmed": "danger"}


# ------------------------------------------------------------------ readers
def read_status(path=STATUS):
    """The state file as a dict, or None when there isn't one (he isn't running)."""
    try:
        with open(path) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def parse_audit(lines, limit=40):
    """The newest `limit` audit lines, newest first, as {t, tool, ok, keys, err, ms}. An
    argument's value never comes through: only the names of the arguments."""
    out = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if not isinstance(e, dict) or not e.get("tool"):
            continue
        args = e.get("args")
        keys = sorted(args) if isinstance(args, dict) else []
        out.append({"t": K.iso_time(e.get("t")), "tool": K.redact(str(e["tool"]))[:48],
                    "ok": e.get("ok") is not False, "keys": [K.redact(k)[:24] for k in keys][:6],
                    "err": K.redact(e.get("err"))[:140] if e.get("err") else None, "ms": e.get("ms")})
        if len(out) >= limit:
            break
    return out


def read_audit(path=AUDIT, limit=40):
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - TAIL_BYTES))
            raw = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    lines = raw.splitlines()
    if len(raw) >= TAIL_BYTES and lines:
        lines = lines[1:]                          # the first may be cut in half
    return parse_audit(lines, limit)


def parse_prs(doc):
    """`gh search prs --json number,title,url,repository,isDraft,updatedAt,createdAt` ->
    [{repo, number, title, url, draft, updated}] newest first."""
    out = []
    for p in doc or []:
        if not isinstance(p, dict):
            continue
        repo = p.get("repository") or {}
        out.append({"repo": repo.get("nameWithOwner") or repo.get("name") or "?", "number": p.get("number"),
                    "title": str(p.get("title") or ""), "url": p.get("url"), "draft": bool(p.get("isDraft")),
                    "updated": K.iso_time(p.get("updatedAt") or p.get("createdAt"))})
    out.sort(key=lambda p: -(p["updated"] or 0))
    return out


class GhError(Exception):
    pass


def fetch_prs(account):
    if not shutil.which("gh"):
        raise GhError("gh isn't installed: install github-cli, then run gh auth login")
    try:
        r = subprocess.run(["gh", "search", "prs", "--author", account, "--state", "open", "--limit", "30", "--json",
                            "number,title,url,repository,isDraft,updatedAt,createdAt"],
                           capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        raise GhError("GitHub didn't answer in 30 s")
    if r.returncode:
        err = (r.stderr or "").strip()
        if "auth login" in err or "not logged" in err.lower() or "authentication" in err.lower():
            raise GhError("gh isn't signed in: run gh auth login")
        raise GhError(K.redact(err.splitlines()[-1] if err else f"gh exited {r.returncode}")[:140])
    return parse_prs(json.loads(r.stdout or "[]"))


# ------------------------------------------------------------------ demo readings
_NOW = time.time()
DEMO_STATUS = {"state": "thinking", "mood": "calm", "muted": False, "conversation": False, "shown": True,
               "switch": "on", "unread": 2, "voice": "main", "voice_mode": "auto", "model": "qwen3-32b",
               "watching": None, "suppressed": None}
DEMO_AUDIT = [
    {"t": _NOW - 40, "tool": "read_file", "ok": True, "keys": ["path"], "err": None, "ms": 3},
    {"t": _NOW - 95, "tool": "github", "ok": True, "keys": ["repo", "what"], "err": None, "ms": 412},
    {"t": _NOW - 160, "tool": "run_shell", "ok": True, "keys": ["command", "cwd"], "err": None, "ms": 1820},
    {"t": _NOW - 600, "tool": "pr_open", "ok": True, "keys": ["base", "repo", "title"], "err": None, "ms": 2210},
    {"t": _NOW - 900, "tool": "run_shell", "ok": False, "keys": ["command"],
     "err": "refused: a push to a default branch", "ms": 0},
    {"t": _NOW - 1500, "tool": "web_search", "ok": True, "keys": ["query"], "err": None, "ms": 940},
    {"t": _NOW - 2400, "tool": "wallpaper", "ok": True, "keys": ["theme"], "err": None, "ms": 120},
    {"t": _NOW - 3600, "tool": "memory.note", "ok": True, "keys": ["text"], "err": None, "ms": 18},
    {"t": _NOW - 5400, "tool": "lab_status", "ok": True, "keys": [], "err": None, "ms": 230},
    {"t": _NOW - 7200, "tool": "k8s_restart", "ok": False, "keys": ["name", "namespace"],
     "err": "denied: needs your approval", "ms": 0},
] + [{"t": _NOW - 3 * 3600 - k * 997 - (k * k % 7) * 1800, "tool": ("read_file", "github", "run_shell", "web_search")[k % 4],
      "ok": k % 11 != 3, "keys": ["path"], "err": None if k % 11 != 3 else "refused: outside his work folder", "ms": 40}
     for k in range(60)]
DEMO_AUDIT.sort(key=lambda a: -a["t"])
DEMO_PRS = [{"repo": "example-org/desk-tools", "number": 42, "title": "docs: say how the clock panel picks its time zone",
             "url": "https://github.com/example-org/desk-tools/pull/42", "draft": False, "updated": _NOW - 1800},
            {"repo": "example-org/desk-tools", "number": 41, "title": "clock: draw the seconds hand only with full motion",
             "url": "https://github.com/example-org/desk-tools/pull/41", "draft": False, "updated": _NOW - 3 * 3600},
            {"repo": "example-org/theme-kit", "number": 7, "title": "tide: a calmer accent for high contrast",
             "url": "https://github.com/example-org/theme-kit/pull/7", "draft": True, "updated": _NOW - 26 * 3600}]


# ------------------------------------------------------------------ the panel
class VectorPanel(K.KitPanel):
    name, title = "vector", "VECTOR"
    description = "VECTOR at a glance: what he's doing, his emergency switch, what he did last, his pull requests for you"
    category, reads = "system", "VECTOR's state file and audit log, and his pull requests through your gh login"
    width, height = 460, 300
    interval = 2.0
    sizes = {
        "compact": ((240, 120), (380, 190), (280, 140)),
        "standard": ((400, 240), (620, 400), (460, 300)),
        "wide": ((640, 200), (1100, 360), (800, 260)),
        "tall": ((380, 420), (560, 900), (420, 600)),
        "large": ((660, 480), (1200, 900), (800, 600)),
    }
    default_size = "standard"
    settings = [{"key": "account", "label": "VECTOR's GitHub account", "kind": "text", "default": "bromigodev",
                 "hint": "The account his pull requests come from"}]

    @classmethod
    def available(cls):
        """(False, why) without VECTOR on this machine: the gallery greys the card and leaves
        it out of Add (docs/plugins.md)."""
        if K.demo() or shutil.which("bromigos-holo") or os.path.exists(STATUS):
            return True
        return (False, "VECTOR isn't installed (bromigos-vector)")

    def __init__(self, cfg=None, wake=None):
        super().__init__(cfg, wake)
        self.status, self.audit, self.audit_m = None, [], None
        self.installed = bool(shutil.which("bromigos-holo")) or os.path.exists(STATUS)
        self.phase = 0.0
        self.pending_switch = 0.0
        if K.demo():
            self.status, self.audit, self.installed = dict(DEMO_STATUS), list(DEMO_AUDIT), True
            self.prs = None
            self.demo_prs = list(DEMO_PRS)
        else:
            self.demo_prs = None
            self.prs = self.poller(lambda: fetch_prs(self.conf.get("account", "bromigodev")), every=300, name="prs")
        self.tick()

    def tick(self):
        if K.demo():
            self._animate()
            return
        seen = time.monotonic() - self.drawn_at < 30
        self.status = read_status()
        if not seen:
            return
        try:
            m = os.path.getmtime(AUDIT)
        except OSError:
            m = None
        if m != self.audit_m:
            self.audit_m = m
            self.audit = read_audit(limit=400) or []
        self._animate()

    def _animate(self):
        st = (self.status or {}).get("state")
        self.animating = K.motion() == "full" and st in ("listening", "thinking", "speaking")

    def toggle_switch(self):
        """Off at once; on only after a YES in the confirmation menu (bromigos vector switch toggle)."""
        self.pending_switch = time.monotonic()
        K.spawn(["bromigos", "vector", "switch", "toggle"])

    # ---- drawing
    def pr_state(self):
        if self.demo_prs is not None:
            return self.demo_prs, None, time.time() - 120
        return self.prs.data, self.prs.error, (time.time() - (time.monotonic() - self.prs.at)) if self.prs.at else None

    def draw(self, cr, w, h):
        cls = self.size_class(w, h)
        st = self.status
        sw = (st or {}).get("switch")
        top = D.frame(cr, w, h, self.title, None)
        self.region(0, 0, w - 130, 34, "VECTOR, the desktop's AI: his state from his daemon's state file, his recent "
                    "tool calls from his audit log (arguments' values left out), and his open pull requests")
        if not self.installed:
            self.empty(cr, w, h, top, "VECTOR ISN'T INSTALLED",
                       "Install bromigos-vector, then start him with bromigos-holo vector (or Super+V).")
            return
        self._switch(cr, w, sw)
        x0, x1 = 16, w - 16
        if cls == "compact":
            self._compact(cr, st, x0, x1, top, h)
            return
        if cls == "standard":
            y = self._state(cr, st, x0, x1, top, big=False)
            prs, err, _at = self.pr_state()
            self._actions(cr, x0, x1, y + 4, h - 34, limit=None)
            self._pr_line(cr, x0, x1, h - 28, prs, err)
        elif cls == "wide":
            c1 = x0 + max(230, (x1 - x0) * 0.28)
            c2 = c1 + (x1 - c1) * 0.52
            if h >= 300:
                self._state(cr, st, x0, c1 - 16, top, big=True, stacked=True, h=h)
            else:
                self._state(cr, st, x0, c1 - 16, top, big=True, nrows=max(1, int((h - top - 40) // 17)))
            self._actions(cr, c1, c2 - 16, top, h - 12)
            self._prs(cr, c2, x1, top, h - 12)
        elif cls == "tall":
            y = self._state(cr, st, x0, x1, top, big=True, h=h)
            need = 18 + 18 * max(1, len(self.audit))
            mid = min(y + 4 + need + 10, y + (h - y) * 0.6)
            self._actions(cr, x0, x1, y + 4, mid - 8)
            self._prs(cr, x0, x1, mid, h - 12)
        else:
            y = self._state(cr, st, x0, x0 + 300, top, big=True, h=h)
            self._activity(cr, x0 + 320, x1, top + 2, y - 6)
            split = x0 + (x1 - x0) * 0.56
            self._actions(cr, x0, split - 18, y + 4, h - 12, detail=True)
            self._prs(cr, split, x1, y + 4, h - 12)

    def _switch(self, cr, w, sw):
        """The emergency switch, top right: what it is now, and a click that toggles it."""
        on = sw != "off"
        lbl = "SWITCH ON" if on else "SWITCH OFF"
        lay = D.layout(cr, lbl, 10, "semibold", 0.08)
        bw = lay.get_pixel_size()[0] + 22
        bx, by = w - 16 - bw, 8
        col = "phosphor" if on else "danger"
        D.src(cr, col, 0.18 if on else 0.9)
        cr.rectangle(bx, by, bw, 18)
        cr.fill()
        D.src(cr, col, 0.9)
        cr.set_line_width(1)
        cr.rectangle(bx + 0.5, by + 0.5, bw - 1, 17)
        cr.stroke()
        D.dot(cr, bx + 8, by + 9, 2.6, "void" if not on else col, glow=False)
        D.text(cr, bx + 14, by + 2, lbl, 10, "void" if not on else col, "semibold", spacing=0.08)
        busy = time.monotonic() - self.pending_switch < 8
        tip = ("VECTOR's emergency switch is ON. Click to switch him OFF at once: it stops his commands, his turn and "
               "his speech." if on else
               "VECTOR's emergency switch is OFF. Click to switch him back on: a confirmation menu asks for YES first.")
        self.region(bx, by, bw, 18, tip + (" (asked just now)" if busy else "")
                    + " The same switch as Super+Ctrl+Esc and the bar's power mark.", self.toggle_switch)

    def _orb(self, cr, cx, cy, r, st):
        """His construct, small: a ring in the mood's colour, the state's arc in it. Turns
        slowly while he listens, thinks or speaks, with full motion only."""
        state = (st or {}).get("state") or "off"
        mood = MOODS.get((st or {}).get("mood"), "phosphor")
        _word, col = STATES.get(state, (state.upper(), "soft"))
        if (st or {}).get("switch") == "off":
            col, mood = "danger", "danger"
        cr.new_path()
        D.src(cr, "void", 0.85)
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.fill()
        cr.set_line_width(1.5)
        D.src(cr, mood, 0.55)
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.stroke()
        live = state in ("listening", "thinking", "speaking")
        t = time.monotonic() if (live and K.motion() == "full") else 0.0
        cr.set_line_width(max(2.5, r * 0.14))
        D.src(cr, col, 0.95 if state != "off" else 0.35)
        a0 = t * 1.6 - math.pi / 2
        span = math.pi * (1.4 if live else 2.0 if state == "idle" else 0.6)
        cr.arc(cx, cy, r * 0.7, a0, a0 + span)
        cr.stroke()
        if state == "speaking":
            k = 0.5 + 0.5 * math.sin(t * 6) if t else 0.6
            D.dot(cr, cx, cy, r * (0.14 + 0.12 * k), col)
        else:
            D.dot(cr, cx, cy, r * 0.16, col, glow=state != "off")

    def _compact(self, cr, st, x0, x1, top, h):
        r = max(16, min(36, (h - top - 14) / 2))
        cy = top + r + 2
        self._orb(cr, x0 + r, cy, r, st)
        state = (st or {}).get("state") or "off"
        word, col = STATES.get(state, (state.upper(), "soft"))
        if (st or {}).get("switch") == "off":
            word, col = "SWITCHED OFF", "danger"
        D.text(cr, x0 + 2 * r + 14, top + 4, word, 15, col, "bold", spacing=0.08, width=x1 - x0 - 2 * r - 14)
        mood = (st or {}).get("mood")
        sub = " · ".join(b for b in ((mood or "").upper(), "MUTED" if (st or {}).get("muted") else "",
                                     f"{st.get('unread')} UNREAD" if st and st.get("unread") else "") if b)
        if sub:
            D.label(cr, x0 + 2 * r + 14, top + 28, sub, "dim", size=10)
        self.region(x0, top, x1 - x0, 2 * r + 4, self._state_tip(st))
        y = cy + r + 12
        if h - y >= 22 and self.audit:                     # room: the last thing he did
            a = self.audit[0]
            D.dot(cr, x0 + 4, y + 7, 2.6, "phosphor" if a["ok"] else "danger", glow=False)
            D.text(cr, x0 + 14, y, a["tool"], 11, "soft" if a["ok"] else "danger", "medium", width=(x1 - x0) * 0.6)
            D.label(cr, x1, y + 1, K.ago(a["t"]), "static", size=10, align="right")
            self.region(x0, y - 1, x1 - x0, 17, f"His last tool call: {a['tool']}, {K.ago(a['t'])} ago"
                        + ("" if a["ok"] else f", refused ({a['err'] or 'no reason given'})"))

    def _activity(self, cr, x0, x1, top, bottom):
        """His tool calls per hour over the last 24 hours, refused ones stacked in red."""
        if x1 - x0 < 120 or bottom - top < 50:
            return
        now = time.time()
        ok, bad = [0] * 24, [0] * 24
        for a in self.audit:
            if not a["t"] or now - a["t"] >= 86400:
                continue
            i = 23 - int((now - a["t"]) // 3600)
            (ok if a["ok"] else bad)[i] += 1
        D.label(cr, x0, top, "TOOL CALLS · 24 H", "dim", size=10)
        total, refused = sum(ok) + sum(bad), sum(bad)
        D.label(cr, x1, top, f"{total} · {refused} REFUSED" if refused else f"{total}", "danger" if refused else "soft",
                size=10, align="right")
        gy, gh = top + 18, bottom - top - 30
        bw = (x1 - x0) / 24
        peak = max(1, max(o + b for o, b in zip(ok, bad)))
        D.src(cr, "void", 0.7)
        cr.rectangle(x0, gy, x1 - x0, gh)
        cr.fill()
        for i in range(24):
            hh_ok = gh * ok[i] / peak
            hh_bad = gh * bad[i] / peak
            if ok[i]:
                D.src(cr, "phosphor", 0.75)
                cr.rectangle(x0 + i * bw + 1, gy + gh - hh_ok, bw - 2, hh_ok)
                cr.fill()
            if bad[i]:
                D.src(cr, "danger", 0.9)
                cr.rectangle(x0 + i * bw + 1, gy + gh - hh_ok - hh_bad, bw - 2, hh_bad)
                cr.fill()
            self.region(x0 + i * bw, gy, bw, gh, f"{23 - i} to {24 - i} hours ago: {ok[i]} tool call(s) went through"
                        + (f", {bad[i]} refused" if bad[i] else ""))
        D.label(cr, x0, gy + gh + 3, "24H AGO", "static", size=10)
        D.label(cr, x1, gy + gh + 3, "NOW", "static", size=10, align="right")

    def _state_tip(self, st):
        if not st:
            return "VECTOR isn't running: there's no state file. Start him with bromigos-holo vector (or Super+V)."
        state = st.get("state") or "?"
        bits = [f"VECTOR is {state}" + (" (his emergency switch is off)" if st.get("switch") == "off" else "")]
        if st.get("mood"):
            bits.append(f"mood {st['mood']}")
        if st.get("voice"):
            bits.append(f"voice {st['voice']}" + (" (pinned)" if st.get("voice_mode") not in (None, "auto") else ""))
        if st.get("model"):
            bits.append(f"model {st['model']}")
        if st.get("muted"):
            bits.append("muted")
        if st.get("conversation"):
            bits.append("in hands-free conversation")
        if st.get("unread"):
            bits.append(f"{st['unread']} replies you haven't seen")
        return ", ".join(bits) + "."

    def _state(self, cr, st, x0, x1, top, big=False, stacked=False, h=None, nrows=None):
        """The orb, his state in words and the readings beside it. Returns the y under it."""
        r = 30 if big else 22
        if stacked and h:
            r = max(24, min(46, (h - top - 90) / 2.4))
        cx, cy = x0 + r, top + r + 4
        self._orb(cr, cx, cy, r, st)
        state = (st or {}).get("state") or "off"
        word, col = STATES.get(state, (state.upper(), "soft"))
        if (st or {}).get("switch") == "off":
            word, col = "SWITCHED OFF", "danger"
        if stacked:
            tx, ty = x0, cy + r + 10
        else:
            tx, ty = x0 + 2 * r + 16, top + 2
        D.text(cr, tx, ty, word, 16 if big else 14, col, "bold", spacing=0.08, width=x1 - tx)
        self.region(x0, top, x1 - x0, (ty - top) + 22, self._state_tip(st))
        rows = []
        if st:
            rows.append(("MOOD", (st.get("mood") or "?").upper(), MOODS.get(st.get("mood"), "soft"),
                         "His mood: calm, excited, concerned or alarmed"))
            rows.append(("VOICE", (st.get("voice") or "?") + ("" if st.get("voice_mode") in (None, "auto") else " · PINNED"),
                         "soft", "The voice he speaks in" + ("" if st.get("voice_mode") in (None, "auto")
                                                             else ", pinned (bromigos-holo voice auto unpins it)")))
            if st.get("model"):
                rows.append(("MODEL", str(st["model"]), "soft", "The model his brain runs on"))
            flags = [f for f in ("MUTED" if st.get("muted") else "", "TALKING" if st.get("conversation") else "",
                                 f"{st['unread']} UNREAD" if st.get("unread") else "") if f]
            if flags:
                rows.append(("NOW", " · ".join(flags), "amber" if st.get("unread") else "soft",
                             "Muted: his voice is off. Talking: hands-free conversation. Unread: replies you haven't seen"))
        y = ty + 24
        if not st:
            D.text(cr, tx, ty + 22, "Start him with bromigos-holo vector, or Super+V.", 10, "static", "regular",
                   width=x1 - tx, wrap=True)
            y = ty + 40
        lim = nrows if nrows is not None else 4 if big else 2
        colw = (x1 - tx) / (2 if not big and not stacked else 1)
        for i, (k, v, c, tip) in enumerate(rows[:lim]):
            if not big and not stacked:
                rx, ry = tx + (i % 2) * colw, y + (i // 2) * 17
            else:
                rx, ry = tx, y + i * 17
            lw = D.label(cr, rx, ry, k, "dim", size=10)[0]
            D.text(cr, rx + max(lw + 8, 54), ry - 1, v, 11, c, "medium", width=colw - max(lw + 8, 54) - 6)
            self.region(rx, ry - 2, colw, 17, tip)
        n = min(lim, len(rows))
        used = (math.ceil(n / 2) if not big and not stacked else n) * 17
        return max(y + used + 4, cy + r + 10)

    def _actions(self, cr, x0, x1, top, bottom, limit=None, detail=False):
        D.label(cr, x0, top, "RECENT ACTIONS", "dim", size=10)
        D.rule(cr, x0 + 130, top + 7, x1, "dim", 0.3)
        y = top + 18
        acts = self.audit
        if not acts:
            exists = os.path.exists(AUDIT) or K.demo()
            msg = "Nothing in his audit log yet." if exists else "No audit log yet: he hasn't used a tool."
            D.text(cr, x0, y, msg, 11, "static", "regular", width=x1 - x0)
            self.region(x0, top, x1 - x0, 36, f"His tool calls are logged in {K.home_path(AUDIT)}")
            return
        row = 30 if detail else 18
        n = max(1, int((bottom - y) // row))
        for a in acts[:min(n, limit or n)]:
            col = "phosphor" if a["ok"] else "danger"
            D.dot(cr, x0 + 4, y + 7, 2.6, col, glow=False)
            when = K.ago(a["t"])
            right = when if a["ok"] else f"REFUSED · {when}"
            rw = D.label(cr, x1, y + 1, right, "static" if a["ok"] else "danger", size=10, align="right")[0]
            D.text(cr, x0 + 14, y, a["tool"], 11, "soft" if a["ok"] else "danger", "medium",
                   width=max(20, x1 - x0 - 14 - rw - 8))
            if detail:
                sub = (a["err"] if a["err"] else ("(" + ", ".join(a["keys"]) + ")" if a["keys"] else "()")
                       + (f" · {a['ms'] / 1000:.1f} s" if a.get("ms") and a["ms"] >= 100 else ""))
                D.text(cr, x0 + 14, y + 14, sub, 10, "amber" if a["err"] else "static", "regular", width=x1 - x0 - 14)
            tip = (f"{a['tool']} at {K.clock(a['t'])} ({when} ago)" if a["t"] else a["tool"]) \
                + (f", with {', '.join(a['keys'])}" if a["keys"] else "") \
                + (": it went through" if a["ok"] else ": refused or failed") \
                + (f" ({a['err']})" if a["err"] else "") + ". Argument values are never shown."
            self.region(x0, y - 1, x1 - x0, row - 1, tip)
            y += row

    def _pr_line(self, cr, x0, x1, y, prs, err):
        D.rule(cr, x0, y - 6, x1, "dim", 0.3)
        if err:
            D.label(cr, x0, y, "PULL REQUESTS: " + ("SIGN IN TO GH" if "gh" in err else "UNREACHABLE"), "amber", size=10)
            self.region(x0, y - 2, x1 - x0, 18, f"His pull requests: {err}")
            return
        if prs is None:
            D.label(cr, x0, y, "PULL REQUESTS: CHECKING…", "static", size=10)
            self.region(x0, y - 2, x1 - x0, 18, "Asking GitHub for his open pull requests")
            return
        ready = [p for p in prs if not p["draft"]]
        D.label(cr, x0, y, f"{len(ready)} PULL REQUEST(S) FOR YOU" + (f" · {len(prs) - len(ready)} DRAFT" if len(prs) > len(ready)
                                                                  else ""), "phosphor" if ready else "static", size=10)
        first = ready[0] if ready else None
        if first:
            D.text(cr, x1, y - 1, f"{first['repo'].split('/')[-1]}#{first['number']}", 11, "soft", "medium", align="right")
        self.region(x0, y - 2, x1 - x0, 18, f"His open pull requests: {len(ready)} ready for your review"
                    + (f", {len(prs) - len(ready)} still drafts" if len(prs) > len(ready) else "")
                    + (f". Newest: {first['repo']}#{first['number']} {first['title']}. Click to open it." if first else ""),
                    (lambda u=first["url"]: K.open_url(u)) if first else None)

    def _prs(self, cr, x0, x1, top, bottom):
        prs, err, at = self.pr_state()
        acct = self.conf.get("account", "bromigodev")
        D.label(cr, x0, top, "HIS PULL REQUESTS", "dim", size=10)
        D.rule(cr, x0 + 160, top + 7, x1, "dim", 0.3)
        y = top + 18
        if err:
            D.text(cr, x0, y, err, 11, "amber", "regular", width=x1 - x0, wrap=True)
            self.region(x0, top, x1 - x0, 50, f"His pull requests ({acct}) are read through your own gh login: {err}")
            return
        if prs is None:
            D.text(cr, x0, y, "Checking…", 11, "static", "regular")
            self.region(x0, top, x1 - x0, 36, f"Asking GitHub for {acct}'s open pull requests")
            return
        if not prs:
            D.text(cr, x0, y, "None open. Nothing waits on you.", 11, "static", "regular", width=x1 - x0)
            self.region(x0, top, x1 - x0, 36, f"{acct} has no open pull requests (checked every 5 minutes)")
            return
        row = 36
        n = max(1, int((bottom - y) // row))
        for p in prs[:n]:
            D.text(cr, x0, y, p["title"], 11, "static" if p["draft"] else "soft", "medium", width=x1 - x0)
            x = x0
            if p["draft"]:
                x += self.chip(cr, x, y + 16, "draft", "static", "A draft: he hasn't asked for review yet") + 6
            else:
                x += self.chip(cr, x, y + 16, "review", "phosphor", "Ready: waiting for your review") + 6
            D.text(cr, x, y + 17, f"{p['repo']}#{p['number']} · {K.ago(p['updated'])}", 10, "static", "regular",
                   width=x1 - x)
            self.region(x0, y - 1, x1 - x0, row - 2, f"{p['repo']}#{p['number']}: {p['title']}"
                        + (" (draft)" if p["draft"] else " — waiting for your review")
                        + f", updated {K.ago(p['updated'])} ago. Click to open it.", lambda u=p["url"]: K.open_url(u))
            y += row
        if len(prs) > n:
            D.label(cr, x1, bottom - 10, f"+{len(prs) - n} MORE", "static", size=10, align="right")
            self.region(x1 - 90, bottom - 12, 90, 14, f"{len(prs) - n} more open pull requests by {acct}")


PANEL = VectorPanel
LAYOUT = {"visible": False}
