"""VECTOR: his brain (the model and where it runs), his voice (his own mute, auto or a
pinned voice), the conversation mode, his keys, his emergency switch, and what he
remembers (docs/settings.md, "VECTOR").

His state is read the way he keeps it, without starting him: the voice's mute through
`bromigos-holo mute status` (that form never starts him), the pinned voice from
~/.local/state/bromigos/vector-voice-mode, the emergency switch from its markers (the same
files his terminal and tools read before every command: vector's holo/vector/switch.py),
and, while he runs, what he publishes in $XDG_RUNTIME_DIR/bromigos-vector.json (the
conversation mode, the model that answered). Pinning a voice or turning the conversation on
starts him; the hints say so.

The emergency switch. Switching VECTOR off is allowed at any time, by anyone: flipping the
switch off runs `bromigos-holo off` at once. Turning him back on stays the operator's own
action, which this page may trigger and nothing else may. While he's off his tools refuse
everything that changes something, so he can't even open this window; and when he's on
he can launch apps and open files and URLs, but he can't click. So the only way to switch
him back on is flipping the switch on, which only opens a dialog (the switch stays off),
and then the dialog's "Turn him on" (Cancel is the default, so Enter or Esc never says
yes): `_rearm_confirmed` is the one function that runs `bromigos-holo on`, and it's only
ever passed to ctx.confirm. There is deliberately no other path: no GAction or app/window
action (a GtkApplication exports those on D-Bus, where anything of the user's can call
them), no command-line flag, no `bromigos settings vector#…` that clicks (a search result
or a page key only focuses its row), no URL handler, no file this page watches, and
nothing a render or the Reset button does touches it. desktop/tests/test_vector_guard.py
checks that this stays so."""
import json
import os
import tomllib

from gi.repository import GLib, Gtk

from bromigos_settings import Entry, Page


def _esc(text):
    """Text for a row's title or subtitle (they take Pango markup): &, < and > escaped."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

HOLO = "bromigos-holo"
MEMORY = ["bromigos", "memory"]
STATE = os.path.join(os.path.expanduser("~"), ".local/state/bromigos")
SWITCH_KEY = "SUPER+CTRL+ESCAPE"
VOICES = [("auto", "Auto"), ("main", "Main"), ("robot", "Robot"), ("scientist", "Scientist"), ("floor", "Floor"),
          ("notify", "Notify")]


def _config():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return base


def vector_toml():
    """His vector.toml as he resolves it (holo/paths.py): the user's, the old place, the
    machine's, the package's."""
    c = _config()
    for p in (os.path.join(c, "bromigos/vector/vector.toml"), os.path.join(c, "bromigos/holo/vector.toml"),
              "/etc/bromigos/vector/vector.toml", "/usr/lib/bromigos/vector/vector.toml"):
        if os.path.isfile(p):
            try:
                with open(p, "rb") as f:
                    return p, tomllib.load(f)
            except (OSError, ValueError):
                return p, {}
    return None, {}


def live():
    """What he publishes while he runs (None when he doesn't)."""
    rt = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    try:
        with open(os.path.join(rt, "bromigos-vector.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def pinned():
    try:
        with open(os.path.join(STATE, "vector-voice-mode")) as f:
            return f.read().strip() or "auto"
    except OSError:
        return None


def _switch_marks():
    """The emergency switch's markers (vector's switch.py): any one there means he's off."""
    run = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return (os.path.join(run, "bromigos-vector-switch", "off"), os.path.join(STATE, "vector-switch", "off"),
            os.path.join(STATE, "vector-shell-off"))


def switched_off():
    """(off, by): the switch's own rule, a marker there or a markers' folder swapped for a
    symlink; `by` from the marker (who flipped it)."""
    marks = _switch_marks()
    off = any(os.path.lexists(p) for p in marks) or any(os.path.islink(os.path.dirname(p)) for p in marks[:2])
    by = None
    for p in marks[:2]:
        try:
            with open(p) as f:
                by = (json.load(f) or {}).get("by")
            break
        except (OSError, ValueError, AttributeError):
            continue
    return off, by


def _when(t):
    return (t or "")[:16].replace("T", " ") or "?"


class VectorPage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.page = ctx.page()
        self.page.set_reset(self.reset, what="His voice back to auto and unmuted. His keys are on the Shortcuts "
                                             "page; his emergency switch is never changed by a reset.")
        self.key_rows = []
        self.mem_rows = []
        self.mem = None
        self.running = None
        self._brain()
        self._voice()
        self._keys()
        self._switch()
        self._memory()
        self.refresh()
        GLib.timeout_add_seconds(5, self._tick)

    # ------------------------------------------------------------------ building
    def _brain(self):
        self.brain_group = self.ctx.group(self.page, "His brain", "The model he thinks with, and where it runs.",
                                          key="brain")
        self.brain_rows = [self.ctx.loading(self.brain_group, "Asking where his brain runs…")]

    def _voice(self):
        ctx = self.ctx
        g = ctx.group(self.page, "His voice", "VECTOR's own voice. The desktop's one mute (his voice and the "
                                             "theme's sounds together) is on the Sound page.")
        self.mute_row = ctx.switch_row(
            g, "Mute his voice", "He still answers in writing", key="mute",
            hint="Mutes or unmutes VECTOR's voice only (bromigos-holo mute on|off); never starts him",
            on_toggle=self._mute,
            advanced={"file": "~/.local/state/bromigos/vector-voice-muted", "runs": "bromigos-holo mute on|off"})
        self.voice_row = ctx.combo_row(
            g, "Voice", "", options=VOICES, current=None, key="voice", on_select=self._voice_mode,
            hint="Auto lets him pick the voice for each line; any other pins that voice for every line. "
                 "Choosing starts him if he isn't running",
            advanced={"file": "~/.local/state/bromigos/vector-voice-mode", "runs": "bromigos-holo voice MODE"})
        self.voice_row.set_use_markup(True)      # a ComboRow's text isn't markup by default
        self.conv_row = ctx.switch_row(
            g, "Conversation mode", "", key="conversation", on_toggle=self._conversation,
            hint="Hands-free: he listens on the echo-cancelled microphone and answers without a key "
                 "(SUPER+SHIFT+E). Turning it on starts him if he isn't running",
            advanced={"runs": "bromigos-holo conversation", "reads": "$XDG_RUNTIME_DIR/bromigos-vector.json"})
        ctx.row(g, "The desktop's mute and sounds", "Mute everything, the output device, the cues",
                hint="Opens the Sound page", key="sound", activate=lambda: ctx.open_page("sound"))

    def _keys(self):
        self.keys_group = self.ctx.group(self.page, "His keys", "Show him, talk to him, the conversation mode. "
                                                               "Change… opens the \"press the new shortcut\" window.",
                                         key="keys")

    def _switch(self):
        ctx = self.ctx
        g = ctx.group(self.page, "Emergency switch",
                      "VECTOR runs commands as you, inside his limits (no sudo, no secrets, no real money). "
                      f"This switch stops him at once. Also {SWITCH_KEY}, or the power mark on the bar.")
        self.switch_row = ctx.switch_row(
            g, "VECTOR", "", key="switch", on_toggle=self._switch_flipped,
            hint="Off: VECTOR stops at once (his running commands, his answer, his speech) and changes nothing "
                 "until you switch him back on. On: asks first; only you can",
            advanced=[("Reads", "~/.local/state/bromigos/vector-switch/off · "
                                "$XDG_RUNTIME_DIR/bromigos-vector-switch/off (either one: off)"),
                      ("Runs", "bromigos-holo off (any time) · bromigos-holo on (only you, after the dialog)"),
                      ("Keys", SWITCH_KEY + " (off at once; on asks first)")])
        ctx.note(g, "Only you switch him back on: nothing else in Settings does, not a search, a link or Reset.",
                 "note", hint="VECTOR can launch apps and open files while he's on, but he can't click a button or "
                              "answer a dialog; while he's off he can't do even that")

    def _memory(self):
        ctx = self.ctx
        self.mem_group = ctx.group(self.page, "What he remembers", "His conversations, and the notes he keeps "
                                                                   "between them. Clearing keeps a copy you can bring "
                                                                   "back.", key="memory-group")

    # ------------------------------------------------------------------ state
    def refresh(self):
        self._sync_local()
        self.ctx.run([HOLO, "mute", "status"], self._got_mute)
        self.ctx.json(["bromigos", "target", "--json"], self._got_targets)
        self.ctx.json(["bromigos", "keys", "list", "--all", "--json"], self._got_keys)
        self.ctx.json(MEMORY + ["--json"], self._got_memory)

    def _tick(self):
        if self.page.get_mapped():
            self._sync_local()
            self.ctx.run([HOLO, "mute", "status"], self._got_mute)
        return True

    def _sync_local(self):
        d = live()
        mode = (d or {}).get("voice_mode") or pinned()
        self.voice_row.set_quiet(mode or "auto")
        self.voice_row.set_subtitle(_esc(
            ("auto: he picks the voice for each line" if mode in (None, "auto") else f"pinned: every line in {mode}")
            + (" · he runs" if d else " · he isn't running")))
        conv = bool((d or {}).get("conversation"))
        self.conv_row.set_quiet(conv)
        self.conv_row.set_subtitle("On: he's listening" if conv else
                                   ("Off" if d else "Off (he isn't running; turning it on starts him)"))
        off, by = switched_off()
        self.switch_row.set_quiet(not off)
        self.switch_row.set_subtitle(_esc(
            (f"Off{f' (switched off by {by})' if by else ''}: his terminal runs nothing and his tools change "
             "nothing. He can still talk") if off else "On: he can act within his limits"))
        (self.switch_row.add_css_class if off else self.switch_row.remove_css_class)("bromigos-warn")
        self.running = d

    def _got_mute(self, ok, out, _err):
        said = out.strip()
        if said in ("muted", "unmuted"):
            self.mute_row.set_quiet(said == "muted")
            self.mute_row.set_sensitive(True)
        else:
            self.mute_row.set_sensitive(False)
            self.mute_row.set_subtitle("bromigos-holo isn't installed (bromigos-vector)")

    def _got_targets(self, doc, err):
        ctx = self.ctx
        g = self.brain_group
        ctx.clear_group(g, self.brain_rows)
        path, conf = vector_toml()
        llm = conf.get("llm") or {}
        model = llm.get("model") or ((self.running or {}).get("model"))
        where = llm.get("base_url") or "his fallbacks (no endpoint set)"
        rows = self.brain_rows
        rows.append(ctx.row(g, "Model", f"{model or 'not set'} · {where}", key="model",
                            hint=f"From {path or 'no vector.toml'}: the model he asks and the OpenAI-compatible "
                                 "endpoint it's served at",
                            advanced={"file": path or "~/.config/bromigos/vector/vector.toml", "key": "[llm]"}))
        svc = next((s for s in (doc or {}).get("services") or [] if s.get("service") == "llm"), None)
        if svc is None:
            rows.append(ctx.failed(g, ["bromigos", "target", "--json"], err or "no llm service"))
        else:
            uses = svc.get("uses")
            lines = [f"{e['target']}: {e.get('detail')}" for e in svc.get("entries") or []
                     if not e.get("ok") and (not uses or e["target"] != uses["target"])]
            rows.append(ctx.row(g, "Answering now",
                                (f"{uses['target']} ({uses['engine']})" if uses else "nothing answers now") +
                                ("\n" + "\n".join(lines) if lines else ""), key="answering",
                                hint="Each place his brain may run, in order, and whether it answers "
                                     "(bromigos target)", advanced={"runs": "bromigos target --json"}))
        rows.append(ctx.row(g, "Change his brain", "The questions again: the model and its endpoint "
                                                   "(bromigos setup vector)", key="brain-change",
                            hint="Opens VECTOR's brain setup in a terminal",
                            buttons=[("Change…", lambda: ctx.terminal(["bromigos", "setup", "vector"]),
                                      "bromigos setup vector, in a terminal")],
                            advanced={"file": "~/.config/bromigos/vector/vector.toml", "key": "[llm] base_url, model",
                                      "runs": "bromigos setup vector"}))
        rows.append(ctx.row(g, "Where AI runs", "Homelab, this machine or the cloud, for his brain, voice and "
                                                "hearing", hint="Opens Creation targets", key="targets",
                            activate=lambda: ctx.open_page("targets")))

    def _got_keys(self, doc, err):
        ctx = self.ctx
        ctx.clear_group(self.keys_group, self.key_rows)
        rows = [r for r in (doc or {}).get("all") or [] if r.get("section") == "VECTOR"]
        if doc is None:
            self.key_rows.append(ctx.failed(self.keys_group, ["bromigos", "keys", "list", "--all", "--json"], err))
            return
        if not rows:
            self.key_rows.append(ctx.note(self.keys_group, "No VECTOR keys are bound (is bromigos-vector installed?)",
                                          "warn", hint="His keys come from the defaults' vector.lua"))
            return
        for n, r in enumerate(rows):
            what = r["what"].removeprefix("VECTOR: ")
            buttons = []
            if r.get("movable"):
                buttons.append(("Change…", lambda r=r: self._rebind(r), f"Press a new key for {what} "
                                                                       f"(now {r['display']})"))
            self.key_rows.append(ctx.row(
                self.keys_group, what[:1].upper() + what[1:], r["display"], key="keys" if n == 0 else None,
                hint=f"{r['display']}: {r['what']}" + ("" if r.get("movable") else f" ({r.get('why') or 'fixed'})"),
                buttons=buttons, advanced={"file": "~/.config/bromigos/keys.toml",
                                           "runs": f"bromigos keys bind --from \"{r['keys']}\""}))

    def _got_memory(self, doc, err):
        ctx = self.ctx
        ctx.clear_group(self.mem_group, self.mem_rows)
        if not doc or doc.get("ok") is False:
            self.mem_rows.append(ctx.failed(self.mem_group, MEMORY + ["--json"], (doc or {}).get("error") or err))
            return
        self.mem = doc
        h, m = doc["history"], doc["memory"]
        hsub = (f"{h['conversations']} conversations, {h['messages']} messages, {_when(h['first'])} to "
                f"{_when(h['last'])}" if h["messages"] else "Nothing yet")
        self.mem_rows.append(ctx.row(
            self.mem_group, "Conversation history", hsub, key="history",
            hint="Every message you and VECTOR exchanged, kept on this machine; his history panel reads it",
            buttons=[("Clear…", lambda: self._clear("history"), "Moves his conversation history into an archive "
                                                                "(Undo brings it back)")] if h["exists"] else [],
            advanced={"file": h["file"], "runs": "bromigos memory clear history --yes"}))
        store = m.get("store") or ("local" if m["local"] else m["backend"])
        if store == "gnosis":
            msub = (f"{m['notes']} notes" if m.get("notes") is not None else "His notes") + " in your homelab's Gnosis"
        elif m["local"]:
            msub = (f"{m['notes']} notes on this machine" if m.get("notes") is not None else "No notes yet") + \
                   (f" · {m['note']}" if m.get("note") else "")
        else:
            msub = m.get("note") or f"kept by {m['backend']}"
        where = "in your homelab's Gnosis" if store == "gnosis" else "on this machine"
        clear_mem = [("Clear…", lambda: self._clear("memory"), f"Deletes the notes he keeps {where} (a copy "
                                                               "is archived here; Undo brings them back)")] \
            if store == "gnosis" or (m["local"] and m.get("notes")) else []
        self.mem_rows.append(ctx.row(
            self.mem_group, "Long-term memory", msub, key="memory",
            hint="The facts he files between conversations and recalls when they matter",
            buttons=clear_mem, advanced={"file": m["file"], "key": f"backend = {m['backend']}",
                                         "runs": "bromigos memory clear memory --yes"}))
        undo = [("Undo the last clear", self._undo, "Puts the last clear back")] if doc.get("can_undo") else []
        self.mem_rows.append(ctx.row(
            self.mem_group, "Export", "A copy of both in a folder you choose, readable only by you", key="export",
            hint="Writes his history and notes (as JSON) into a new folder",
            buttons=[("Export…", self._export, "Choose a folder for the copy")] + undo,
            advanced={"runs": "bromigos memory export DIR", "note": f"archives: {doc.get('archive')}"}))

    # ------------------------------------------------------------------ changes
    def _holo(self, args, said, undo=None):
        def done(ok, out, err):
            text = (out or err).strip()
            if not ok or text.startswith("error") or text in ("voice unavailable", "unknown command"):
                self.ctx.toast(f"VECTOR: {text or 'no answer'}"[:200], timeout=8)
            else:
                self.ctx.toast(said, undo=undo)
            self._sync_local()
            self.ctx.run([HOLO, "mute", "status"], self._got_mute)
        self.ctx.run([HOLO] + args, done)

    def _mute(self, on):
        self._holo(["mute", "on" if on else "off"], f"His voice {'muted' if on else 'unmuted'}",
                   undo=lambda: self._holo(["mute", "off" if on else "on"], "Undone"))

    def _voice_mode(self, mode):
        old = (live() or {}).get("voice_mode") or pinned() or "auto"
        if mode == old:
            return
        self._holo(["voice", mode], f"Voice: {mode}", undo=lambda: self._holo(["voice", old], "Undone"))

    def _conversation(self, on):
        if bool((live() or {}).get("conversation")) == on:
            return
        self._holo(["conversation"], f"Conversation mode {'on' if on else 'off'}",
                   undo=lambda: self._holo(["conversation"], "Undone"))

    def _rebind(self, r):
        self.ctx.change(["bromigos", "keys", "bind", "--from", r["keys"], "--json"],
                        lambda d: "; ".join(d.get("notes") or ["Saved"])[:160],
                        undo=["bromigos", "keys", "undo", "--json"], done=lambda _d: self.refresh())

    def _switch_flipped(self, on):
        if not on:
            self._holo(["off", "--from=settings"], "VECTOR is off")
            return
        self.switch_row.set_quiet(False)          # stays off until the dialog's yes (see the docstring)
        self._rearm()

    def _rearm(self):
        self.ctx.confirm(
            "Switch VECTOR back on?",
            "He'll be able to run commands and use his tools as you again, within his limits (no sudo, no "
            "secrets, no real money), until he's switched off. Only do this if you switched him off and want "
            "him back.",
            "Turn him on", self._rearm_confirmed, destructive=True)

    def _rearm_confirmed(self):
        # The only call that switches him back on: reached from the confirm dialog's yes alone (see the docstring)
        self._holo(["on", "--from=settings"], "VECTOR is on again")

    def _export(self):
        def chosen(path):
            self.ctx.change(MEMORY + ["export", path, "--json"], lambda d: d.get("said") or "Exported",
                            done=lambda d: self._got_memory(d, ""))

        fd = Gtk.FileDialog(title="Export VECTOR's history and memory to…")

        def done(d, res):
            try:
                f = d.select_folder_finish(res)
            except GLib.Error:
                return
            if f is not None and f.get_path():
                chosen(f.get_path())
        fd.select_folder(self.ctx.window, None, done)

    def _clear(self, what):
        h, m = self.mem["history"], self.mem["memory"]
        notes = f"His {m['notes']} notes" if m.get("notes") is not None else "His notes"
        body = (f"His {h['messages']} messages move into an archive; his history panel starts empty."
                if what == "history" else
                f"{notes} in your homelab's Gnosis are deleted (a copy is archived here)."
                if m.get("store") == "gnosis" else f"{notes} are deleted (a copy is archived).")
        self.ctx.confirm(f"Clear VECTOR's {'conversation history' if what == 'history' else 'memory'}?",
                         body + " Undo brings it back.", "Clear", lambda: self.ctx.change(
                             MEMORY + ["clear", what, "--yes", "--json"], lambda d: d.get("said") or "Cleared",
                             undo=MEMORY + ["undo", "--json"], done=lambda d: self._got_memory(d, "")),
                         destructive=True)

    def _undo(self):
        self.ctx.change(MEMORY + ["undo", "--json"], lambda d: d.get("said") or "Undone",
                        done=lambda d: self._got_memory(d, ""))

    def reset(self):
        """His voice back to auto and unmuted (never the emergency switch)."""
        old_mode = (live() or {}).get("voice_mode") or pinned() or "auto"
        if old_mode != "auto":
            self._holo(["voice", "auto"], "Voice: auto")
        self._holo(["mute", "off"], "His voice: auto, unmuted")
        return None


def build(ctx):
    p = VectorPage(ctx)
    p.page._vector = p
    return p.page


def refresh(widget):
    widget._vector.refresh()


PAGE = Page(
    id="vector", title="VECTOR", group="vector", order=10, build=build, refresh=refresh, docs="settings.md#vector",
    icon="avatar-default-symbolic system-users-symbolic", summary="brain, voice, keys, emergency switch, memory",
    intro="The SpacePort's caretaker on your desktop: the model he thinks with, his voice, his keys, his emergency "
          "switch, and what he remembers.",
    keywords=["assistant", "ai", "vector", "holo", "caretaker"],
    entries=[
        Entry("model", "His model", ["brain", "llm", "endpoint", "base url"], "His brain"),
        Entry("answering", "What answers now", ["brain status", "llm target"], "His brain"),
        Entry("brain-change", "Change his brain", ["setup vector", "model setup"], "His brain"),
        Entry("mute", "Mute VECTOR's voice", ["vector mute", "silence vector", "quiet"], "His voice"),
        Entry("voice", "VECTOR's voice", ["pinned voice", "auto voice", "robot", "scientist", "floor"], "His voice"),
        Entry("conversation", "Conversation mode", ["hands-free", "listen", "SUPER+SHIFT+E"], "His voice"),
        Entry("keys", "VECTOR's keys", ["push to talk", "talk key", "wake key", "SUPER+V", "SUPER+E"], "His keys"),
        Entry("switch", "VECTOR's emergency switch", ["kill switch", "turn vector off", "stop vector", "shell",
                                                       "terminal", "commands", "SUPER+CTRL+ESCAPE"],
              "Emergency switch"),
        Entry("history", "Conversation history", ["chat log", "clear history", "transcript"], "What he remembers"),
        Entry("memory", "Long-term memory", ["notes", "forget", "clear memory", "privacy"], "What he remembers"),
        Entry("export", "Export his history and memory", ["backup", "download", "copy"], "What he remembers"),
    ])
