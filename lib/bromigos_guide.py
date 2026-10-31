"""VECTOR's spoken guide: the scripted lines of the installers and the welcome tours, and a
small player for their clips (docs/voice-guide.md).

The lines live in one catalogue, lib/guide/lines.toml (installed as
/usr/share/bromigos/guide/lines.toml). Each line has a stable id, such as installer.edition
or tour.phone, and its words. The clips are Opus files in guide/clips/, made at build time
in VECTOR's designed voice by tools/voice/make-clips.py; guide/clips/manifest.json says
which clip speaks which words.

    import bromigos_guide as guide
    guide.line("installer.disk.alongside", who="Windows")    # the caption
    g = guide.Guide("gui")          # or "console", for the text installer and the server tour
    g.play("installer.edition")     # returns at once; the next play() or g.stop() cuts it off
    g.toggle()                      # Ctrl+Alt+V: mute or unmute, remembered

The player stays quiet while a screen reader talks (Orca on the desktop; speakup, espeakup
or Fenrir on the console), when the guide is off or muted, and when there is no sound
device: then it says so once (Guide.notice) and stays silent.

Sound goes through PipeWire (pw-play, which reads Opus itself) when a PipeWire session is
running, else ALSA (aplay), with ffmpeg or opusdec decoding the Opus first.

The guide's settings, on or off and muted, are one small JSON file:
$BROMIGOS_GUIDE_STATE, else $XDG_STATE_HOME/bromigos/voice-guide.json
(~/.local/state/bromigos/voice-guide.json). The boot option bromigos.voice=off turns the
guide off for that boot.
"""
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess

try:
    import tomllib
except ImportError:          # Python before 3.11
    tomllib = None

HERE = os.path.dirname(os.path.realpath(__file__))
SHARE = "/usr/share/bromigos/guide"

HOTKEY = "Ctrl+Alt+V"                      # mutes and unmutes the guide, in every surface
GTK_ACCEL = "<Control><Alt>v"
# Textual reads Ctrl+Alt+V as ctrl+v on terminals without the kitty keyboard protocol (the
# Linux console, most SSH clients); a focused Input takes ctrl+v as paste first
TEXTUAL_KEYS = "ctrl+alt+v,ctrl+v"

SERIAL_TTY = re.compile(r"^/dev/(ttyS|ttyAMA|ttyUSB|ttyACM|hvc|ttysclp|ttyPS|ttymxc)\d")


# ------------------------------------------------------------------ the catalogue

def data_dir():
    """The guide's folder: $BROMIGOS_GUIDE_DIR, this checkout's lib/guide, else the package's."""
    env = os.environ.get("BROMIGOS_GUIDE_DIR")
    if env:
        return env
    here = os.path.join(HERE, "guide")
    if os.path.isfile(os.path.join(here, "lines.toml")):
        return here
    return SHARE


_cat = {}


def catalogue(folder=None):
    """{id: {"text", "where", "say", "fallback"}}, read once per change of the file."""
    path = os.path.join(folder or data_dir(), "lines.toml")
    st = os.stat(path)
    hit = _cat.get(path)
    if hit and hit[0] == (st.st_mtime_ns, st.st_size):
        return hit[1]
    if tomllib is None:
        raise RuntimeError("the voice guide needs Python 3.11 or newer (tomllib)")
    with open(path, "rb") as f:
        doc = tomllib.load(f)
    lines = {}
    for key, v in doc.items():
        if not isinstance(v, dict):
            continue                      # format = 1
        if not isinstance(v.get("text"), str) or not v["text"].strip():
            raise ValueError(f"{path}: line {key} has no text")
        lines[key] = {"text": v["text"], "where": v.get("where", ""), "say": v.get("say") or {},
                      "fallback": v.get("fallback") or {}}
    _cat[path] = ((st.st_mtime_ns, st.st_size), lines)
    return lines


def has(line_id, folder=None):
    return line_id in catalogue(folder)


def pick(line_id, short=False, folder=None):
    """The id to use: `<id>.short` for a narrow surface when the catalogue has one."""
    if short and has(line_id + ".short", folder):
        return line_id + ".short"
    return line_id


def line(line_id, folder=None, **values):
    """A line's words, its {names} filled in: the caption. "" for an id the catalogue lacks."""
    v = catalogue(folder).get(line_id)
    if v is None:
        return ""
    return _fill(v["text"], {**v["fallback"], **values})


def _fill(text, values):
    class Keep(dict):
        def __missing__(self, k):
            return "{" + k + "}"
    return text.format_map(Keep(values))


def text_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def clip_key(line_id, values=None):
    """A clip's name in the manifest: the id, and the values it was spoken with."""
    if not values:
        return line_id
    return line_id + "[" + ",".join(f"{k}={values[k]}" for k in sorted(values)) + "]"


def clip_file(key, text):
    """The clip's file name: the key in plain letters, then the first 12 of the text's hash."""
    slug = re.sub(r"[^a-z0-9.]+", "-", key.lower().replace("[", "--").replace("]", "")).strip("-")
    return f"{slug}-{text_hash(text)[:12]}.opus"


def clips(folder=None):
    """Every clip the catalogue needs: [(key, id, values, spoken text)]. A line with a {name}
    gets one clip per value in its `say` list; one without, a single clip."""
    out = []
    for lid, v in catalogue(folder).items():
        say = v["say"]
        if not say:
            out.append((lid, lid, {}, v["text"]))
            continue
        names = sorted(say)
        combos = [{}]
        for n in names:
            combos = [{**c, n: val} for c in combos for val in say[n]]
        for c in combos:
            out.append((clip_key(lid, c), lid, c, _fill(v["text"], c)))
    return out


def spoken(line_id, folder=None, **values):
    """(clip key, the words it says) for a line as shown with these values: a value with no
    clip of its own uses its first word's clip, or the line's fallback value's."""
    v = catalogue(folder).get(line_id)
    if v is None:
        return None, ""
    chosen = {}
    for n, options in v["say"].items():
        val = values.get(n, v["fallback"].get(n))
        if val not in options:
            first = str(val or "").split(" ")[0]
            val = first if first in options else v["fallback"].get(n, options[0])
        chosen[n] = val
    return clip_key(line_id, chosen), _fill(v["text"], chosen)


def manifest(folder=None):
    try:
        with open(os.path.join(folder or data_dir(), "clips", "manifest.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"clips": {}}


def opus_tags(path):
    """An Ogg Opus file's comments ({"BROMIGOS_GUIDE_ID": ...}), read from its second packet."""
    with open(path, "rb") as f:
        data = f.read(65536)
    at = data.find(b"OpusTags")
    if at < 0:
        return {}
    p = at + 8
    vendor = int.from_bytes(data[p:p + 4], "little")
    p += 4 + vendor
    n = int.from_bytes(data[p:p + 4], "little")
    p += 4
    tags = {}
    for _ in range(n):
        ln = int.from_bytes(data[p:p + 4], "little")
        p += 4
        k, _, val = data[p:p + ln].decode("utf-8", "replace").partition("=")
        tags[k.upper()] = val
        p += ln
    return tags


def problems(folder=None):
    """What's wrong between the catalogue and the clips: [] when every line has a clip that
    says its words, and no clip is left over. tools/voice/make-clips.py --check prints these."""
    folder = folder or data_dir()
    cdir = os.path.join(folder, "clips")
    have = manifest(folder).get("clips", {})
    out, used = [], set()
    for key, _lid, _vals, text in clips(folder):
        m = have.get(key)
        if not m:
            out.append(f"{key}: no clip")
            continue
        h = text_hash(text)
        if m.get("text_sha256") != h:
            out.append(f"{key}: its clip says older words (run tools/voice/make-clips.py)")
            continue
        if m.get("file") != clip_file(key, text):
            out.append(f"{key}: the manifest names {m.get('file')}, not {clip_file(key, text)}")
            continue
        path = os.path.join(cdir, m["file"])
        if not os.path.isfile(path):
            out.append(f"{key}: {m['file']} is missing")
            continue
        tags = opus_tags(path)
        if tags.get("BROMIGOS_GUIDE_TEXT_SHA256") != h or tags.get("BROMIGOS_GUIDE_ID") != key:
            out.append(f"{key}: {m['file']} doesn't carry this line's id and text hash")
        used.add(m["file"])
    for key in sorted(set(have) - {k for k, *_ in clips(folder)}):
        out.append(f"{key}: in the manifest, but no line uses it")
    if os.path.isdir(cdir):
        for f in sorted(os.listdir(cdir)):
            if f.endswith(".opus") and f not in used:
                out.append(f"{f}: a clip no line uses")
    return out


# ------------------------------------------------------------------ settings

DEFAULTS = {"enabled": True, "muted": False}


def state_path():
    env = os.environ.get("BROMIGOS_GUIDE_STATE")
    if env:
        return env
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(base, "bromigos", "voice-guide.json")


def settings(path=None):
    """{"enabled", "muted"}: the saved choice over the defaults."""
    out = dict(DEFAULTS)
    try:
        with open(path or state_path()) as f:
            doc = json.load(f)
        out.update({k: bool(doc[k]) for k in DEFAULTS if k in doc})
    except (OSError, ValueError, TypeError):
        pass
    return out


def save_settings(values, path=None):
    path = path or state_path()
    doc = settings(path)
    doc.update({k: bool(v) for k, v in values.items() if k in DEFAULTS})
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w") as f:
            json.dump(doc, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except OSError:
        pass                 # a read-only home: the choice lasts this run
    return doc


def boot_option(root="/"):
    """bromigos.voice= on the kernel command line: True (on), False (off) or None (not given)."""
    try:
        with open(os.path.join(root, "proc/cmdline")) as f:
            words = f.read().split()
    except OSError:
        return None
    for w in reversed(words):
        if w.startswith("bromigos.voice="):
            return w.split("=", 1)[1].lower() not in ("0", "off", "no", "false")
    return None


# ------------------------------------------------------------------ the machine

def _processes(root):
    proc = os.path.join(root, "proc")
    try:
        pids = [p for p in os.listdir(proc) if p.isdigit()]
    except OSError:
        return
    for p in pids:
        try:
            with open(os.path.join(proc, p, "comm")) as f:
                comm = f.read().strip()
        except OSError:
            continue
        try:
            with open(os.path.join(proc, p, "cmdline"), "rb") as f:
                argv = [a.decode("utf-8", "replace") for a in f.read().split(b"\0") if a]
        except OSError:
            argv = []
        yield comm, argv


def _named(comm, argv, names):
    if comm in names:
        return comm
    for a in argv[:2]:                       # a script: python3 /usr/bin/orca
        b = os.path.basename(a)
        if b in names:
            return b
    return None


def screen_reader(ui="gui", root="/"):
    """The screen reader talking on this surface, or None: Orca for the desktop; speakup
    (its synth set), espeakup or Fenrir for the console."""
    if ui == "console":
        try:
            with open(os.path.join(root, "sys/accessibility/speakup/synth")) as f:
                synth = f.read().strip()
            if synth and synth != "none":
                return "speakup"
        except OSError:
            pass
        names = {"espeakup", "fenrir", "fenrir-daemon"}
    else:
        names = {"orca"}
    for comm, argv in _processes(root):
        hit = _named(comm, argv, names)
        if hit:
            return hit
    return None


def sound_cards(root="/"):
    try:
        with open(os.path.join(root, "proc/asound/cards")) as f:
            return [ln for ln in f if re.match(r"^\s*\d+\s+\[", ln)]
    except OSError:
        return []


def output(ui="gui", root="/", env=None, which=shutil.which, tty=None):
    """How this machine can play a clip: ("pw-play", None), ("aplay", decoder) or
    (None, why not, in plain words). Over SSH the speakers are someone else's: nothing."""
    env = os.environ if env is None else env
    if env.get("SSH_CONNECTION") or env.get("SSH_TTY"):
        return None, "You're connected over SSH, so VECTOR's voice stays quiet. His words are on screen."
    if ui == "console":
        if tty is None:
            try:
                tty = os.ttyname(0)
            except OSError:
                tty = ""
        if SERIAL_TTY.match(tty or ""):
            return None, "This is a serial console, so there's nothing to play VECTOR's voice on."
    pw = which("pw-play", path=env.get("PATH"))
    runtime = env.get("XDG_RUNTIME_DIR") or ""
    remote = env.get("PIPEWIRE_REMOTE") or "pipewire-0"
    sock = remote if os.path.isabs(remote) else os.path.join(runtime, remote)
    if pw and runtime and os.path.exists(sock):
        return "pw-play", None
    cards = sound_cards(root)
    if not cards:
        return None, "No sound device, so VECTOR's voice stays quiet. His words are still on screen."
    if not which("aplay", path=env.get("PATH")):
        return None, "No sound player (aplay or pw-play), so VECTOR's voice stays quiet."
    for dec in ("ffmpeg", "opusdec"):
        if which(dec, path=env.get("PATH")):
            return "aplay", dec
    return None, "No Opus decoder (ffmpeg or opusdec) for aplay, so VECTOR's voice stays quiet."


def _commands(backend, decoder, clip):
    """The argv lists that play `clip`: one, or a decoder piped into aplay."""
    if backend == "pw-play":
        return [["pw-play", "--media-role", "Accessibility", clip]]
    dec = (["ffmpeg", "-nostdin", "-loglevel", "error", "-i", clip, "-f", "wav", "-"] if decoder == "ffmpeg"
           else ["opusdec", "--quiet", clip, "-"])
    return [dec, ["aplay", "-q", "-"]]


# ------------------------------------------------------------------ the player

class Guide:
    """One surface's voice: play(id) speaks a line and returns at once; the next play() or
    stop() cuts it off. Safe to call from GTK's or Textual's main loop: nothing blocks.

    ui: "gui" (the graphical installer, the desktop tour) or "console" (the text installer,
    the server tour). notify: called once with a plain sentence when the guide can't speak
    (no sound device). root, env, tty: stand-ins for tests."""

    def __init__(self, ui="gui", notify=None, folder=None, state=None, root="/", env=None, tty=None):
        self.ui = ui
        self.folder = folder
        self.state = state
        self.root = root
        self.env = os.environ if env is None else env
        self.tty = tty
        self.notify = notify
        self.notice = None                 # the plain sentence, once there's no sound device
        self._out = None
        self._procs = []
        s = settings(self.state)
        boot = boot_option(root)
        self.enabled = s["enabled"] if boot is None else boot
        self.muted = s["muted"]

    # the machine, checked once: a sound device doesn't come and go during an install
    def backend(self):
        if self._out is None:
            self._out = output(self.ui, self.root, self.env, shutil.which, self.tty)
            if self._out[0] is None and self.notice is None:
                self.notice = self._out[1]
                if self.notify:
                    try:
                        self.notify(self.notice)
                    except Exception:
                        pass
        return self._out[0]

    def screen_reader(self):
        return screen_reader(self.ui, self.root)

    def status(self):
        """"off", "muted", "screen-reader", "no-sound" or "on"."""
        if not self.enabled:
            return "off"
        if self.muted:
            return "muted"
        if self.screen_reader():
            return "screen-reader"
        if self.backend() is None:
            return "no-sound"
        return "on"

    def describe(self):
        """The status in plain words, for a hover hint or a status line."""
        return {
            "off": "VECTOR's voice guide is off.",
            "muted": f"VECTOR's voice is muted. {HOTKEY} turns it back on.",
            "screen-reader": "VECTOR stays quiet while your screen reader talks.",
            "no-sound": self.notice or "No sound device, so VECTOR's voice stays quiet.",
            "on": f"VECTOR reads each step aloud. {HOTKEY} mutes him.",
        }[self.status()]

    def clip(self, line_id, **values):
        """The clip's path for a line as shown, or None: no clip, or one that says other words."""
        key, text = spoken(line_id, self.folder, **values)
        if key is None:
            return None
        m = manifest(self.folder).get("clips", {}).get(key)
        if not m or m.get("text_sha256") != text_hash(text):
            return None
        path = os.path.join(self.folder or data_dir(), "clips", m["file"])
        return path if os.path.isfile(path) else None

    def play(self, line_id, **values):
        """Speak a line (cutting off the one before). True when it started."""
        self.stop()
        if self.status() != "on":
            return False
        path = self.clip(line_id, **values)
        if path is None:
            return False
        backend, decoder = self._out
        argvs = _commands(backend, decoder, path)
        try:
            prev = None
            for i, argv in enumerate(argvs):
                last = i == len(argvs) - 1
                p = subprocess.Popen(argv, stdin=prev.stdout if prev else subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL if last else subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, env=dict(self.env), start_new_session=True)
                if prev is not None:
                    prev.stdout.close()          # the decoder sees aplay go
                self._procs.append(p)
                prev = p
        except OSError:
            self.stop()
            return False
        return True

    def speaking(self):
        return any(p.poll() is None for p in self._procs)

    def stop(self):
        """Cut the line off now (Esc, the next step)."""
        for p in self._procs:
            if p.poll() is None:
                try:
                    os.killpg(p.pid, signal.SIGTERM)
                except OSError:
                    pass
        for p in self._procs:
            try:
                p.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except OSError:
                    pass
        self._procs = []

    def set_muted(self, muted):
        self.muted = bool(muted)
        if self.muted:
            self.stop()
        save_settings({"muted": self.muted}, self.state)

    def toggle(self):
        """Ctrl+Alt+V: mute or unmute, remembered. Returns whether it's muted now."""
        self.set_muted(not self.muted)
        return self.muted

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        if not self.enabled:
            self.stop()
        save_settings({"enabled": self.enabled}, self.state)
