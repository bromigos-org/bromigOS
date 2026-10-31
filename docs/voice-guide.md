# The voice guide

The voice guide is VECTOR reading his line aloud on each step of the installers and the
welcome tours. VECTOR is bromigOS's AI assistant, with a voice. Each step already shows a
short line from him beside his orb. The voice guide speaks that same line, in his designed
voice, from a small recorded clip. Nothing is generated while you install, so it needs no
network, no model and no graphics card.

The manual explains it for users, in [The installer](../manual/src/installer.md#vectors-voice)
and [The welcome tour](../manual/src/welcome-tour.md#vectors-voice). This page is for
contributors: the files, their format, how the clips are made, and the player.

## The parts

| Part | In the repository | Installed by `bromigos-core` as |
|---|---|---|
| The line catalogue | `lib/guide/lines.toml` | `/usr/share/bromigos/guide/lines.toml` |
| The clips and their manifest | `lib/guide/clips/` | `/usr/share/bromigos/guide/clips/` |
| The reader and the player | `lib/bromigos_guide.py` | `/usr/lib/bromigos/lib/bromigos_guide.py` |
| The clip maker | `tools/voice/make-clips.py` | Not installed: a build tool |
| The tests | `tests/voice-guide/` | Run by the package's `check()` and CI |

The graphical installer, the text installer, the desktop's tour (`bromigos welcome`) and the
server's tour (`bromigos welcome-console`) all read their lines from the catalogue. So a
line's caption and its clip always say the same words.

## The catalogue

`lib/guide/lines.toml` holds every scripted line. Each line is one table. Its quoted name is
the line's id, and an id never changes once code uses it.

```toml
["installer.edition"]
text = "Pick what this computer is for. A server can get the desktop later."
where = "both installers: the edition"

["installer.disk.alongside"]
text = "{who} keeps its files. I'll make room beside it."
where = "both installers: the disk, installing beside another system ({who} is its name)"
say = { who = ["Windows", "the other system"] }
fallback = { who = "the other system" }
```

| Key | What it holds |
|---|---|
| `text` | What VECTOR says, word for word. It is both the caption and the clip's script |
| `where` | Where the line is said, for people reading the file |
| `say` | For a line with a `{name}`: the values that get a clip of their own |
| `fallback` | The value whose clip plays when the real one has no clip |

Ids are `<surface>.<step>`:

| Prefix | Surface |
|---|---|
| `installer.` | Both installers. The step id is the installer's own, with `:` written as `.` (`disk:erase` is `installer.disk.erase`) |
| `installer.<step>.short` | The text installer's version of a line, where its narrow rail says less |
| `tour.` | The desktop's welcome tour |
| `server-tour.` | bromigOS Server's welcome tour |

A clip can't say every name. For `installer.disk.alongside`, "Windows 11" plays the
"Windows" clip, because its first word is in the `say` list. "Ubuntu 24.04" plays the
"the other system" clip. The caption still shows the real name.

## The clips

Each line has one clip, and a line with a `say` list has one clip per value. A clip is a
mono Opus file at 28 kb/s, about 10 KB for a line. All 37 clips come to about 390 KB.

A clip's file name is the line's id, then the first 12 characters of the SHA-256 hash of
its words: `installer.edition-09a74fe69224.opus`. Each clip also carries two tags,
`BROMIGOS_GUIDE_ID` and `BROMIGOS_GUIDE_TEXT_SHA256`. `clips/manifest.json` lists every
clip with its words, their hash, the engine that spoke it and its length.

### Making the clips

Change a line's `text`, then run the clip maker. It speaks only the new and changed lines,
and removes the clips no line uses:

```bash
tools/voice/make-clips.py --work <folder>
```

`<folder>` is where it keeps its socket, its log and the raw recordings. Without
`--work` it uses a new temporary folder. `--all` speaks every line again.

The clip maker starts VECTOR's own voice server, `holo/voice_server.py` from
`bromigos-vector`, as a separate process with its own socket. It never talks to a voice
server that is already running. It needs:

- `bromigos-vector`, or a checkout of it named with `--vector <dir>`.
- VECTOR's voice environment, which `bromigos-holo setup voice` builds. Name another with
  `--python <path>`.
- `ffmpeg` with libopus.

It always speaks with the package's `voice.json`, never your own. That gives every clip
VECTOR's designed caretaker voice (`voices/vector-ref-A.wav`), and never a personal voice
cast.

The engine is your homelab's voice service by default. The clip maker finds it the way
VECTOR does: from your `targets.toml`, your `homelab.toml` voice capability or your private
overlay, read when it runs. Nothing about your lab goes into the repository. To use this
computer's graphics card when there is no lab, add `--engines lab,qwen`. Kokoro is never
used, because it isn't VECTOR's designed voice. If a line comes back from any other
engine, the clip maker stops.

Commit the clips with the change to `lines.toml`. The ISO build then needs no voice model.

### The check

```bash
tools/voice/make-clips.py --check
```

The check needs no voice. It fails when a line has no clip, when a clip says older words
(its recorded hash doesn't match the text), or when a clip is left over. CI's `iso-check`
workflow runs it with the tests:

```bash
PYTHONPATH=lib python -m unittest discover -s tests/voice-guide -v
```

## The player

`bromigos_guide.Guide` plays the clips. The GTK and Textual apps both use it. It never
blocks their main loop.

```python
import bromigos_guide as guide

g = guide.Guide("gui", notify=show_notice)    # "console" for the text installer and the server tour
caption = guide.line("installer.edition")
g.play("installer.edition")                  # returns at once
g.play("installer.disk.alongside", who=who)   # the next play() cuts off the last
g.stop()                                     # Esc, leaving the step
g.toggle()                                   # Ctrl+Alt+V: mute or unmute, remembered
```

| Call | What it does |
|---|---|
| `guide.line(id, **values)` | The line's words, with its `{names}` filled in: the caption |
| `guide.pick(id, short=True)` | The `.short` id when the catalogue has one, else `id` |
| `Guide(ui, notify=None)` | A player for `"gui"` or `"console"`. `notify` gets one plain sentence if there's no sound device |
| `play(id, **values)` | Stops the line before, then speaks this one. `True` when it started |
| `stop()` | Stops at once |
| `speaking()` | Whether a line is playing |
| `toggle()`, `set_muted(bool)` | Mutes or unmutes, and saves it |
| `set_enabled(bool)` | Turns the guide off or on, and saves it |
| `status()` | `on`, `muted`, `off`, `screen-reader` or `no-sound` |
| `describe()` | The status as a sentence, for a hover hint |

`guide.HOTKEY`, `guide.GTK_ACCEL` and `guide.TEXTUAL_KEYS` name the mute key for each
toolkit. On a terminal without the kitty keyboard protocol, such as the Linux console,
Textual reads Ctrl+Alt+V as `ctrl+v`. So the Textual apps bind both.

### How it plays

- **PipeWire** (`pw-play`), when a PipeWire session is running. `pw-play` reads Opus
  itself.
- **ALSA** (`aplay`), when there's no PipeWire session but there is a sound card.
  `ffmpeg` decodes the Opus first, or `opusdec` when there's no `ffmpeg`. The live ISO has
  `alsa-utils` and `ffmpeg`, so the text installer speaks on the console.
- **Nothing**, over SSH, on a serial console, with no sound card, or with no player.
  The guide says so once, through `notify` and `Guide.notice`, and stays silent.

### When it stays quiet

- **A screen reader is running.** On the desktop, that's Orca. On the console, it's
  speakup with a synthesiser set, `espeakup` or Fenrir. The player checks before every
  line, so starting a screen reader mid-install quiets it.
- **It's muted**, with Ctrl+Alt+V.
- **It's off**, from a saved setting or the boot option `bromigos.voice=off`.

### The settings file

The guide's two settings, `enabled` and `muted`, live in one JSON file:

```json
{
  "enabled": true,
  "muted": false
}
```

The file is `$XDG_STATE_HOME/bromigos/voice-guide.json`, which is usually
`~/.local/state/bromigos/voice-guide.json`. `BROMIGOS_GUIDE_STATE` names another file.
On the live ISO it's the live session's file: the graphical installer's user, or root for
the text installer. The installer copies it to the new user's
`~/.local/state/bromigos/voice-guide.json`, so the welcome tour remembers the choice.

The guide is off when there's no file: it speaks once someone turns it on, on the
installer's first step or with Ctrl+Alt+V. On the kernel command line, `bromigos.voice=on`
turns it on for that boot, over the file, and `bromigos.voice=off` (or `0`) turns it off.

`BROMIGOS_GUIDE_DIR` points the reader at another guide folder, such as a test's.
