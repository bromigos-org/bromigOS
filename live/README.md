# The live layer (`bromigos-live`)

The live layer is the program that draws bromigOS's animated background. It also draws
the *decks*, which are full-screen holographic views you open with a key, and the
screensaver, short event animations and the desktop's sound cues. Most of what moves
shows something real, such as CPU load, network traffic or a notification. The few
things that move for their own sake, such as the emblem and the stars, are marked as
decoration in `config.toml`.

This README is for someone working on the live layer's code. To use it, read the
manual's [Themes and worlds](../manual/src/themes-and-worlds.md) and
[Keys](../manual/src/keys.md) pages. Every element of the background is described in
[docs/ELEMENTS.md](docs/ELEMENTS.md).

## What it draws

- **The background.** With the default theme, the Wick, the background is *the den*: a
  painted radio room whose screens, meters and floor the live layer brings to life. The
  den sits behind every window.
- **A world.** A theme with a *world*, such as Mire or Tidewell, replaces the den with its
  own living scene. `bromigos theme set mire` switches to one, and
  `bromigos theme set wick` goes back to the den.
- **Decks.** Full-screen holograms such as the holo deck and the timeline. A deck sits
  over your windows while it's open. [Decks](#decks) lists them.
- **Event animations.** *The intercept* plays at login and unlock: the screen tears and
  the burn-in emblem draws itself. A critical notification gets targeting brackets.
- **Codec calls.** A *codec call* is a short spoken message in VECTOR's voice, shown as a
  small card in the bottom-right corner. Notable real events trigger them, such as a lab
  alert or a long command finishing.
- **The screensaver**, and the **sound cues** for terminals, notifications and the
  intercept.

## How it runs

The live layer is one GTK 3 process, `python -m live.app`. It runs on the system Python
with GtkLayerShell, PyOpenGL, numpy and psutil.

- `bin/bromigos-live` starts the process and supervises it. It restarts the process after
  a crash, and gives up after four crashes in two minutes.
- Hyprland starts it at login with `bromigos-live start --login`. The autostart is in
  `desktop/hypr/bromigos/live.lua`, along with the live layer's keys.
- Only one instance runs per user. `live/instance.py` tracks it by process ID and start
  time, so `stop` and `restart` never stop the wrong process.

The `bromigos-live` package installs:

| Path | What |
|---|---|
| `/usr/lib/bromigos/live/` | The code, shaders, sounds, models and tools from this folder |
| `/usr/bin/bromigos-live` | The command |
| `/usr/share/bromigos/live/config.toml` | The default configuration |

Your own `~/.config/bromigos-live/config.toml` is merged over the default, key by key.
Put only the keys you change in it. The animation switches that `bromigos anim` sets go
in `~/.config/bromigos/live/overrides.toml`, merged over both. The live layer reloads its
config when you save it. Code changes need `bromigos-live restart`.

The homelab decks (Lab, Mind, Ops and Netmap) come with the `bromigos-homelab` package
([docs/homelab.md](../docs/homelab.md)). Your own decks, shader layers and modules are
plugins in `~/.config/bromigos/plugins/live/` ([docs/plugins.md](../docs/plugins.md)).

## Try it

```bash
bromigos-live status                    # running? frame rate, the monitor, its layers
bromigos-live restart                   # after changing the code
bromigos-live timeline                  # open or close a deck
bromigos-live decks                     # every deck installed, and the Tab order
bromigos-live codec "Test call." DECK   # a codec call on the DECK channel
bromigos-live job -- make build         # run a command; a long run ends with a codec call
```

`bromigos-live job` makes a call only when the command ran for at least
`codec.job_min_seconds`, which is 60 seconds by default. Codec calls are rate-limited, so
a test call may wait its turn.

With a world showing, `bromigos-live world` lets you try its reactions:

```bash
bromigos-live world state                          # what the world sees now
bromigos-live world event notify                   # a notification arrives
bromigos-live world set agents a:working,b:needs_you   # hold a signal at a value
bromigos-live world clear                          # back to real readings
```

The header of `bin/bromigos-live` lists every verb.

## Test it

The unit tests need no GPU and no running desktop:

```bash
cd live
python -m unittest discover -s tests
```

They cover the reduced-motion logic, image rows at any screen width, the den's recolour,
the deck catalogue and stopping exactly one instance.

`tools/offscreen.py` renders the background, a world or a deck headless, to PNG frames
or a video. It never touches the desktop. It uses NVIDIA's EGL device when there is one,
and Mesa's otherwise.

```bash
python3 tools/offscreen.py bg out.png 2                       # one background frame at t = 2 s
python3 tools/offscreen.py holodeck out.png                   # a deck
OFF_WORLD=../themes/mire python3 tools/offscreen.py world out.mp4 20   # 20 s of Mire
```

`OFF_SCRIPT` drives a render with timed steps, such as world events and key presses.
`OFF_MOTION=reduced` renders under a motion setting. The tool's header lists all of it.

Four render tests check what the unit tests can't:

| Test | What it checks |
|---|---|
| `tests/offscreen_motion.py` | Reduced motion and the still mode, for the den, a world and the overlays |
| `tests/offscreen_sizes.py` | The background at six screen sizes, from 1280×800 to 3440×1440 |
| `tests/offscreen_retint.py` | The den recoloured for the Wick and the six colour themes |
| `tests/software_session.py` | The daemon on a software renderer: a still frame, at low CPU ([No GPU](#no-gpu)) |

## Decks

A deck is a full-screen hologram. Open one with its key, the radial menu (Super+A), the
desktop menu's HOLOGRAMS group, the app launcher or a `bromigos-live` verb. VECTOR can
open them too.

Only one deck shows at a time. Opening another closes the one showing. Tab closes the
current deck and opens the next in the cycle, which is `[decks] cycle` in `config.toml`.
A deck in the cycle that isn't installed is skipped.

| Deck | Key | Shows | Package |
|---|---|---|---|
| Holo deck | Super+H | This machine's load, the homelab's nodes and a 3D model | `bromigos-live` |
| Timeline | Super+T | The last 72 hours as a ribbon you can scrub | `bromigos-live` |
| Drift map | Super+M | The Bromigos lore as a star chart | `bromigos-live` |
| Swarm | Super+Shift+S | Your Git repositories as a star system, and coding agents as ships | `bromigos-live` |
| Lab | Super+Shift+H | The homelab console: the rack, GPUs and the job queue | `bromigos-homelab` |
| Mind | none | VECTOR's memory and a knowledge base as a constellation | `bromigos-homelab` |
| Ops | none | Pushes, CI runs, deployments and pods, plus VECTOR's tasks | `bromigos-homelab` |
| Netmap | none | The network from the homelab's metrics, with link traffic and latency | `bromigos-homelab` |

The homelab's decks without a key open from the menu, the radial menu, Tab or
`bromigos-live mind`, `ops` or `netmap`. You can bind a key to any deck in your own
`hyprland.lua` ([docs/desktop.md](../docs/desktop.md)).

The app launcher has an entry for every deck and the screensaver. Each entry runs
`bromigos-live open <deck>`. Unlike the bare verb, `open` never closes a deck that's
already open, and it starts the live layer first if it isn't running.

### The holo deck

![The holo deck: this machine's CPU, GPU, memory and video memory as glowing rings, a map
of the homelab's links, and a turning 3D model of the workstation](../docs/images/holo-deck.webp)

The holo deck shows this machine's CPU, GPU, memory and video memory as arc rings. With
a homelab configured, it also shows the homelab's nodes as a constellation. A compact 3D
model from VECTOR's hologram renderer turns on the right, and steps aside when VECTOR
isn't installed. Press N for FIELD NOTES, the notes panel.

### The timeline

![The timeline deck: graphs of the last 72 hours on a ribbon, with a readout of the moment
under the cursor](../docs/images/timeline.webp)

The timeline keeps the last 72 hours of readings, one sample a minute, and lets you
scrub through them. The history is saved in `~/.local/state/bromigos-live/`.

### The Drift map

![The Drift map: a round star chart of named places and factions, joined by lanes, with
the Wick at its edge](../docs/images/drift-map.webp)

The Drift map draws the Bromigos lore catalogue as a star chart. Every light is an entry
and every lane is a relationship. The catalogue ships with `bromigos-live`, in
`/usr/share/bromigos/live/lore/catalog.json`. It's the public lore that bromigos.org
publishes, copied from the site by `tools/lore/sync-catalog.py`. To show another
catalogue of the same shape, set `[driftmap] catalog` to its path in your config.

### Verbs

Some decks take verbs, so VECTOR or a script can point at things in them:

| Deck | Verbs |
|---|---|
| Swarm | `point <repo or agent>`, `focus <repo or agent>`, `clear` |
| Lab | `focus <card or node>`, `clear` |
| Mind | `focus <text>`, `space <knowledge base>`, `clear` |
| Ops | `focus <repo>`, `clear` |
| Netmap | `trace <host>`, `clear` |

For example, `bromigos-live swarm focus bromigOS` flies the Swarm's camera to that
repository.

### Zooming the maps

The Mind, Swarm, Netmap and Drift map decks zoom (`live/zoomcam.py`):

- Scroll to zoom toward the cursor. `+` and `-` zoom too.
- Drag to pan while zoomed in. Shift+drag or the right button turns the view.
- Double-click empty space, or press `0`, to reset.

Detail grows as you zoom in. Mind's clusters open into their documents, the Swarm's
ships get names and the Drift map's minor entries get labels. A label appears only where
there's room for it.

## The screensaver

![The screensaver: the burn-in emblem in a ring, the time, this machine's load as rings,
and a wireframe planet rising in the corner](../docs/images/screensaver.webp)

The idle policy starts the screensaver, after 8 minutes by default
([docs/idle.md](../docs/idle.md)). It shows a wireframe planet lit by the local time of
day, a relay station whose spokes are the homelab's services, this machine's load and
the time. Any key, click or real mouse movement ends it.
[ELEMENTS.md](docs/ELEMENTS.md#screensaver-planet-and-station) has the details.

## Screen sizes

The den and the worlds are painted at 16:9. On a screen of another shape, the scene
renders at the smallest 16:9 size that covers the screen, then is cropped to fit
(`live/cover.py`). It is never stretched.

That means the background image loads at widths such as 1366, 1422 or 2133 pixels. At
those widths, an image's rows of RGB pixels don't line up on 4-byte boundaries.
`live/pixbuf.py` reads every row at its own stride, so nothing shears.
`tests/test_pixbuf.py` checks widths 1 to 17 and the real ones.

## Reduced motion

The user's motion setting reaches everything here through `live/motion.py`. It's set with
`bromigos accessibility motion full|reduced|still`
([docs/accessibility.md](../docs/accessibility.md)).

- `reduced` slows each scene's clock. It removes parallax, flicker, flashes, rotation and
  craft. The intercept crossfades instead of tearing.
- `still` holds one frame. It draws a new frame only when what the frame shows changes.

## No GPU

When the live layer starts, it reads the renderer of GTK's GL context (`GL_RENDERER`).
Mesa's software renderers, llvmpipe, softpipe and swrast, draw on the CPU. At full motion
that takes a dozen CPU cores. A real machine gets one when its GPU driver can't start,
usually after an NVIDIA driver update until the computer restarts
([docs/update.md](../docs/update.md#when-the-kernel-or-the-graphics-driver-changes)).
Most virtual machines have one all the time, because virtio-gpu without 3D has nothing
else. That includes the test VMs and the ISO's.

With a software renderer, the live layer:

- holds a still frame, the `still` motion setting. It draws a new frame at most every 30
  seconds, and only when what it shows changed. Each frame loads the CPU, which changes
  the CPU reading the frame shows, so without the limit it would redraw itself again and
  again;
- runs the decks and the overlays at 10 frames a second at most;
- logs the renderer, and shows a `NO GPU` line in `bromigos-live status`;
- on a real machine, sends one desktop notification a session. A flag in
  `$XDG_RUNTIME_DIR/bromigos-live.software` remembers it was sent. In a virtual machine
  nothing is broken, so there's no notification. The live layer knows a VM from
  `systemd-detect-virt --vm`, or else the CPU's `hypervisor` flag.

A VM holds still too, because full motion costs more than a VM has. In the fresh-machine
test VM, with 4 CPUs at 1280×800, the den at full motion took 2.2 CPUs and still fell
behind, so the live layer kept rebuilding its surface. The still frame took 1% of one CPU.

To allow full motion on a software renderer anywhere, set this in
`~/.config/bromigos-live/config.toml`, or run
`bromigos scene set general.allow_software on`:

```toml
[general]
allow_software = true
```

The code is `live/software.py`. `tests/test_software.py` checks which renderers count, and
the notification. `tests/software_session.py` runs the real daemon on llvmpipe in a
sandbox: a throwaway home, its own `/proc`, a private D-Bus and a headless kwin. It
measures the CPU.

## Performance

| When | Frame rate |
|---|---|
| The desktop is visible | 30 fps |
| Windows are tiled over the desktop | 20 fps |
| Locked, under a fullscreen window, or under a deck | 0 fps |

Measured, the process uses about 7–9% of one CPU core and under 1% of the GPU. A deck
frame takes 0.6–1.7 ms at the median. Heavy readings run only while the deck that needs
them is open.

The background never draws over application windows. Decks do, but only while open.

## Files

| Path | What it does |
|---|---|
| `bin/bromigos-live` | The command and the supervisor |
| `config.toml` | Every switch and setting, with a note on which layers are data and which are decoration |
| `live/app.py` | The daemon: windows, Hyprland and notification events, pause rules, recovery after a monitor change, the control socket |
| `live/instance.py` | One daemon per user, stopped exactly |
| `live/config.py` | Loads and merges the configuration layers |
| `live/scene.py`, `shaders/bg.frag` | The background: the den made live, rain, floor pulses, space, the scanner |
| `shaders/rain.glsl`, `space.glsl`, `denloop.glsl` | The glyph rain, the space layer and the seamless loops |
| `live/plate.py` | Removes the steam and streaks baked into the den painting, in memory, so loops can redraw them |
| `live/traffic.py`, `live/shipmask.py` | The ships crossing the sky, and where they may show |
| `live/world.py`, `actors.py`, `shaders/world*` | Worlds: a theme's whole scene and its actors |
| `live/worldfeed.py`, `activity.py`, `skyclock.py` | Readings only worlds need: coding agents, your activity, the local sky |
| `live/videoloop.py`, `shaders/world_yuv.frag` | Video loops decoded by ffmpeg and drawn on the GPU |
| `live/fireflies.py` | Mire's fireflies |
| `live/cover.py`, `live/pixbuf.py` | Fitting a 16:9 scene to any screen, and reading images at any width |
| `live/decks.py` | The deck catalogue and the Tab cycle (`bromigos-live decks`) |
| `live/deckkit.py` | The base for 3D decks: drag, picking, hover readouts, verbs |
| `live/zoomcam.py` | Zoom and pan for the maps, and label placement |
| `live/swarm_deck.py`, `drift_map.py`, `timeline.py` | The Swarm, the Drift map and the timeline |
| `live/overlays.py` | The overlays: the intercept, the critical-notification brackets, the holo deck, the screensaver, the radial menu |
| `live/glkit.py`, `stage.py`, `gadgets.py` | Drawing primitives, render targets and bloom, gauges and panels |
| `live/holoview.py` | Embeds a compact model from VECTOR's hologram renderer in a deck |
| `live/starship.py`, `models/starship.holo.npz` | The Swarm's ship, a procedural model (`tools/make-starship.py`) |
| `live/constellation.py` | Lays out the homelab's nodes for the holo deck |
| `live/data.py`, `sources.py`, `history.py` | Readings: this machine, the homelab, Git, coding agents, a trade feed, and the 72-hour history |
| `live/homelab.py` | The one place that reads the homelab, through `bromigos-homelab` when it's installed |
| `live/vfeed.py` | Reads VECTOR's event feed |
| `live/codec.py`, `codec_panel.py` | Codec calls: the queue, rate limits, voices and the card |
| `live/watch.py`, `hypr.py` | Watching notifications and the lock, and talking to Hyprland |
| `live/sound.py`, `sounds/` | Sound cues through PipeWire |
| `live/motion.py` | The motion settings and each scene's clock |
| `live/software.py` | No GPU: a software renderer holds the background still |
| `live/emblem.py` | The burn-in emblem, drawn from the canonical SVG |
| `live/lockemblem.py`, `tools/lock-emblem.py` | A turning emblem for the lock screen. Turned off for good (below) |
| `tools/offscreen.py` | Headless renders, for screenshots and tests |
| `applications/` | The app launcher's entries for the decks and the screensaver |
| `tests/` | Unit tests and offscreen render checks |

The data loops in `live/data.py` cover this machine (psutil, and `nvidia-smi` for the
GPU), the homelab's snapshot, and a trade feed's fills. The trade feed is off until
`[fills]` names its URL.

`live/lockemblem.py` once turned the burn-in on hyprlock's lock screen by signalling
hyprlock for each frame. On 2026-10-07 that crashed hyprlock and locked the user out.
Signal-driven animation of hyprlock is retired: `[events] lock_emblem` must stay
`false`.

## State

| Path | What it holds |
|---|---|
| `~/.local/state/bromigos-live/` | `live.log`, the 72-hour history (`history.npz`, `events.jsonl`), `swarm-seen.json`, the `muted` and `codec-quiet` flags |
| `~/.cache/bromigos-live/` | The clean den plate, charts, CI results, the Drift map's layout and spoken lines. All rebuilt when needed |
| `$XDG_RUNTIME_DIR/bromigos-live.sock` | The control socket |
| `$XDG_RUNTIME_DIR/bromigos-live.lock` | Held by the daemon for its whole life, with its process ID and start time. A second daemon exits with code 4 |
| `$XDG_RUNTIME_DIR/bromigos-live.pid` | The supervisor's process ID and start time |
| `$XDG_RUNTIME_DIR/bromigos-live.ctl` | Makes start, stop and restart take turns |

`bromigos-live stop` stops the supervisor, then the daemon. It asks the daemon to quit
over the socket, then sends SIGTERM, then SIGKILL. Each signal goes to a process ID
checked against its start time, never to a name pattern.

The live layer also reads the homelab's snapshot through `bromigos-homelab`, and the
chosen den wallpaper from `~/.local/state/bromigos/wallpaper/`.

## Change it

- To change or add an element of the background, read [docs/ELEMENTS.md](docs/ELEMENTS.md).
  It ends with step-by-step instructions and two worked examples.
- To add a deck or a shader layer without changing this code, write a plugin
  ([docs/plugins.md](../docs/plugins.md)).
- VECTOR's `live-shader-layer` and `update-visualization` skills, in the vector
  repository's `skills/`, walk him through the same work.

## The story behind it

In the Bromigos stories, the den is the radio room of the Wick, a relay station at the
edge of the Drift. The glyph rain is written in the Drift's own script, and the codec
channels are the station's radio bands.
