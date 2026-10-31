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

Colour switches refresh the live layer’s shaders and tinted textures on the next frame,
including paused backgrounds and open overlays. The session stays running. A pinned or held scanner stays visible in the new colours.

Live drawing code uses `col("soft")` and the other palette roles. Shaders use
`THEME_SOFT`, `THEME_PRIMARY` and the other `THEME_` tokens, resolved before compiling.
`tests/test_palette_literals.py` rejects fixed UI colours; its exact exceptions are
geometry, masks, light intensities and the den’s art shades, which are retinted.
Audit personal plugin folders with `python3 tests/test_palette_literals.py --plugins DIR`.
A world may still set its own art colours in `live/world.toml`.

- **The background.** With the default theme, the Wick, the background is *the den*: a
  painted radio room whose screens, meters and floor the live layer brings to life. The
  den sits behind every window.
- **A world.** A theme with a *world*, such as Mire or Tidewell, replaces the den with its
  own living scene. `bromigos theme set mire` switches to one, and
  `bromigos theme set wick` goes back to the den.
- **Decks.** Full-screen holograms such as the holo deck and the timeline. A deck sits
  over your windows while it's open. [Decks](#decks) lists them.
- **Event animations.** *The intercept* plays at login and unlock: the screen tears and
  the burn-in emblem draws itself, full screen and opaque, then cuts back to the desktop.
  A critical notification gets targeting brackets.
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

The static wallpaper is a fallback while the animated background is off or failed.
Starting a healthy background removes the session's `swaybg` surfaces. Theme rendering
and monitor changes keep the still off while that background is active. Switching the
background off, a renderer failure or the daemon exiting restores the still. Other
Wayland sessions, including nested tests, keep their own wallpapers.


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
| `tests/offscreen_retint.py` | The den recoloured for the Wick and the eight colour themes |
| `tests/offscreen_theme_switch.py` | Existing den, pinned scanner and radial surfaces switch Wick → Cinder → Rime → Wick · Tidewell → Wick · Mire → Wick; scanner hues match each palette, and frames match fresh scenes |
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
Its turning emblem shares the login and unlock renderer, with a smoothed circular rim.
[ELEMENTS.md](docs/ELEMENTS.md#screensaver-planet-and-station) has the details.

## The den TV

The den TV turns the den's screens into TVs. A *TV channel* (not an update channel) plays
your own videos as if it were live television: from your Jellyfin or Plex server, a YouTube playlist or channel, or
a folder of video files. Whatever the time, the channel is part-way through something, as
if it had been on all along. The manual's
[Themes and worlds](../manual/src/themes-and-worlds.md#the-den-tv) page is the user's guide.

![The den with a test pattern playing on its big monitor, a speaker in its corner, and the
hover hint under it: the channel, the buttons to change it, the sound, the volume and Full
screen](../docs/images/den-tv.webp)

Each of the den's three screens has a channel list: the big monitor (`big`), the scope
(`wave`) and the small monitor (`emblem`). Channel 1 is the screen's own picture, drawn
exactly as before. Every media channel comes after it, on every screen, unless the
channel's `screens` keeps it to some. Equipment controls appear while Den TV is enabled.
With Den TV disabled, the den is pixel for pixel what it was without the feature.

Every screen plays its own channel at the same time. Each has a player of its own, and
the sound comes from one screen at a time. Two screens on the same channel show the same
moment, like real TV, from one player.

The channel guide (the Den TV app) shows every channel once, with a button for each
screen to tune it. It also adds, removes, reorders and renames channels. See
[The channel guide](#the-channel-guide).

The den TV is the den's only. Mire and Tidewell have no screen to put it on. A world could
name a screen region for it, but none does yet.

### Channels

A channel is a `[[tv.channel]]` table in `~/.config/bromigos-live/config.toml`, or the one
the MEDIA panel's settings describe ([docs/widgets.md](../docs/widgets.md#media)).

```toml
[[tv.channel]]
name = "Saturday"
source = "plex"            # a jellyfin or plex source in homelab.toml; default: the first
library = "TV Shows"       # or collection = "…" or playlist = "…", by its name
order = "shuffle"          # or "in order"
screens = ["big"]          # optional: only these screens (big, wave, emblem); default: every screen

[[tv.channel]]
name = "Sitcoms"
shows = ["Example Show", "Another Show"]   # shows you pick, by title or id
order = "in order"         # take turns: "alternate" says the same; "shuffle" mixes them
bumpers = true             # a few seconds' card opens each item: the channel, what's on, the time

[tv.start]                 # where a screen starts until you change its channel
big = "Saturday"
wave = "Studio"

[[tv.channel]]
name = "Studio"
youtube = "https://www.youtube.com/@example"   # a channel's uploads, or a playlist's address
live = true                # while the channel is live, "Studio LIVE" follows it
keep = "~/Videos/YouTube"  # keep what it plays; keep_all = true keeps every video

[[tv.channel]]
name = "Home movies"
files = "~/Videos/Home"    # a folder, searched through, or a list of files
```

- **The schedule.** The channel's items play end to end from a fixed start, round and
  round, so the time of day says what's on (`lib/bromigos_tv.py`). A playlist plays in its
  own order by default, and anything else shuffled. A shuffle is the same all day and on
  every machine, and a new item slots in without reordering the rest.
- **Shows you pick.** `shows` lists series, `items` single movies and `collections`
  collections, by title or by id. Shuffled, their episodes mix together. In order, they
  take turns like a network's evening block: show A's next episode, then show B's, then
  A's again. Each show goes on from where it left off, day after day, so the channel never
  starts again at S1E1. Where each show is lives in
  `~/.local/state/bromigos-live/tv-rotation.json`, never in `config.toml`. A title is
  matched once and its id remembered (`tv-picks.json`), so a show renamed on the server
  still plays. A title the server doesn't have is named in the guide.
- **Jellyfin and Plex** come through `bromigos-homelab`'s `video` capability
  ([docs/homelab.md](../docs/homelab.md#capabilities)). The server needs a key: a
  Jellyfin API key or a Plex token, in the source's `auth_ref`. A library that a tool fills
  with downloaded YouTube videos plays like any other, by its name: `library = "YouTube"`.
  It plays offline, with no ads, and doesn't break when YouTube changes.
- **YouTube** comes through `yt-dlp`, with no API key (`lib/bromigos_youtube.py`). A
  channel's or playlist's list is read once an hour and cached. A video that won't play,
  such as an age-gated, removed or blocked one, is skipped for a day and logged.
- **Keeping YouTube videos.** With `keep`, each video the TV plays is downloaded into that
  folder, at a low priority, one at a time, and never on battery. The TV plays the kept
  file from then on, so it works offline. The folder can be a NAS share. The layout is the
  one Plex and Jellyfin read: `<Channel>/Season <year>/<date> - <title>.mkv`, or
  `<Playlist>/Season 1/S01E<number> - <title>.mkv`, each with a `.nfo` and a thumbnail.
  `keep_max_gb` caps it, and the oldest kept videos go first. Only files the TV kept are
  ever removed.

The `[tv]` table in `config.toml` has the rest: the stream's quality, full screen's, how
much the den's phosphor tints the picture, the volume a screen starts at, the ducking,
`max_playing` (how many screens decode at once), `cover_opacity` (how opaque a window must
be to count as covering a screen), `screens` (the screens a channel goes on when it
doesn't say: every screen) and `start` (each screen's first channel).

- **Where a screen starts.** `[tv.start]` names a channel for each screen. A screen nobody
  has tuned starts there, so the three screens open on different channels. Once you
  change a screen's channel, it remembers yours, channel 1 included.
- **Bumpers.** With `bumpers = true`, the first five seconds of each item show a card in
  the screen's glass, like a TV network's evening block: the channel's name, "UP NEXT",
  what's on and the time. Every screen on the channel shows it at the same moment.

### How it plays

`live/tv.py` runs the den TV and `live/mpvgl.py` draws the picture:

- **A player per screen.** Each screen showing a media channel has its own libmpv player,
  through python-mpv. Each decodes on the GPU where it can (NVDEC on NVIDIA, VA-API
  elsewhere), for every codec the GPU has, MPEG-2 and MPEG-4 included. Its render API
  draws each frame into that screen's texture, a few hundred pixels across, with mpv's
  cheapest scalers. `bg.frag` draws each texture in its screen's glass, with the tube's
  curve, scanlines, a soft glow and the den's phosphor tint.
- **The stream.** A file the GPU decodes cheaply plays as it is: 1080p or less, 8-bit,
  H.264 or another codec every GPU decodes, under the source's `direct_max_mbps`. mpv seeks
  in it itself, and the server only sends bytes. Anything else, such as a 4K remux or
  10-bit HEVC, is transcoded by the server to the screen's size: 360p for the big monitor
  and 240p for the others at 2560×1440. Full screen plays the file itself.
  `[tv] quality = "direct"` plays every file as it is instead.
- **One stream per screen, ended when it's left.** Each screen opens one stream for what
  it shows, under a device id of its own (`bromigos-den-tv-big` and so on). A screen on the
  same channel as another opens none: it shows the other's frames, or the poster until
  there are some. Changing channel, a new item or a screen going quiet tells the server
  its transcode is over at once. A late or slow transcode is left to play rather than
  chased: it's put back to the clock only when it's two minutes off, since each seek
  starts the server's encoder again. A direct stream is put back when it's three seconds
  off, at most every ten seconds.
- **YouTube, resolved ahead.** A thread of its own asks yt-dlp for each video's stream, no
  taller than the screen, H.264 first. It resolves what's on and the next two ahead and
  keeps each answer for as long as YouTube's address lasts, about six hours. mpv never
  runs yt-dlp for the den, so a short clip starts at once. Until then, the screen shows the
  video's thumbnail. A video YouTube refuses is skipped, and the hint says why.
- **A new channel or item.** The screen shows static, the channel number and the new
  item's poster until the new item's own first frame. The last item's picture is never
  left on the screen, even while the screen is paused.
- **Pausing, screen by screen.** A screen decodes only while it's drawn and in view. A
  second without a frame pauses every screen, so the lock screen, a fullscreen window, a
  deck and the screensaver all stop them. A window over a screen pauses it only when the
  screen is muted. A screen with its sound on plays on behind windows, since you're
  listening. A window more see-through than `[tv] cover_opacity` (0.9) doesn't count.
  Hyprland's own opacity is what counts: a terminal that draws its own see-through
  background looks opaque to it. Coming back, the channel jumps to where it would be now.
- **Motion.** With still motion, or no GPU, each screen shows its item's poster and
  nothing is decoded. With reduced motion, it shows a still frame renewed every 30
  seconds, unless its sound is on.
- **The same channel on two screens.** Both show the same moment, as on real TV, and one
  player decodes for both. The screen with the sound decodes, else the first one in view.
  The other draws the same frame in its own glass.
- **At most `max_playing`.** `[tv] max_playing`, 3 by default, is how many screens decode
  at once. Past it, the screen with the sound plays first, then the big monitor, the scope
  and the small monitor. The others show their posters.
- **Nothing on.** Thirty seconds after a screen's last media channel goes off, its mpv
  closes.
- **The cost.** Measured on an RTX 5070 at 2560×1440, with generated 640×360 H.264 test
  clips, one per screen, each decoded by NVDEC:

  | | The den alone | One screen playing | Three screens playing |
  |---|---|---|---|
  | Offscreen, 30 frames a second: CPU (of one core) | 4.6% | 5.6% | 9.6% |
  | Offscreen: the GPU's shader use | 1.7% | 1.9% | 3.0% |
  | In the nested Hyprland: CPU (of one core) | 10.5% | 11.4% | 17.4% |
  | In the nested Hyprland: the GPU's shader use | 0.1% | 0.4% | 0.5% |

  Three screens cost about 5 to 7% of one core and 1 to 2% of the GPU over the den alone.
  NVDEC's share stays under a percent, since the streams are sized to the screens. A
  1080p H.264 or HEVC video on the big monitor took a frame of the den from 0.46 ms of the
  GPU to 1.1 to 1.2 ms. That is why `max_playing` is 3 by default: even a weak GPU's
  decoder handles three 240p or 360p streams. A folder channel plays its files at their
  own size, so on a weak machine with large files, set `max_playing = 1`.
  (`tests/offscreen_tv.py` with `OFF_MEASURE=20`, and `../desktop/tests/e2e_tv_nested.py
  --measure 15`. The nested numbers include the nested compositor's own work.)

### The pointer, the hint and the keys

The background takes the pointer over the den's screens that have more than one channel,
and nowhere else. Its input region is those screens' rectangles, and the hint's while it
shows, so a click anywhere else on the desktop goes through as before.

| Over a screen | What happens |
|---|---|
| Hover | The hint: what's on, the channel number, ◀ ▶, the speaker, − and + with the volume bar, **FULL**, the server's or YouTube's page and **GUIDE**. A line under them says when the sound can't be heard (the desktop muted, bromigOS muted) or what went wrong on the channel |
| Click | A media channel opens in mpv, full screen with sound, at the same moment. Channel 1 moves to the next channel. |
| Wheel | The next or previous channel, with a burst of static and the channel number on the screen |
| Wheel over the volume bar, or sideways | The volume, shown as a bar on the screen |

Shift and the wheel, and the volume keys, can't reach the den TV. The background never
has the keyboard, so Hyprland tells it about neither. Taking the volume keys over while
the pointer is over the TV would mean rebinding them, and a live layer that stopped
mid-hover would leave them rebound.

Full screen is a normal mpv window. It takes the screen's volume, and the server's key
goes to mpv in a file only you can read, never on its command line. Closing it brings the
TV back at the live position, with its sound as it was.

The keys act on the screen under the pointer. With the pointer elsewhere, they act on the
screen with the sound, else the first showing a media channel, else the big monitor.

| Key | What it does |
|---|---|
| Super+Alt+P | The channel full screen with sound |
| Super+Alt+. and Super+Alt+, | The next and previous channel |
| Super+Alt+M | The screen's sound on or off |
| Super+Alt+G | The channel guide |

### Sound

The TV is silent until you turn its sound on: the speaker in the hint, Super+Alt+M,
`bromigos-live tv sound on`, or turning the volume up. The sound comes from one screen at a
time. Turning it on for one screen turns it off on the others, and a small speaker on the
screen shows where it comes from. Each screen remembers its channel, its sound and its
volume, from 0 to 100, in `~/.local/state/bromigos-live/tv.json`.

- PipeWire shows the TV as **bromigOS den TV**, in the mixer and Settings › Sound.
- With the sound off, no audio is decoded at all.
- bromigOS's mute (Super+Shift+M, `bromigos mute`) silences it.
- When the desktop's own output is muted, the hint says "Your desktop is muted".
- The lock screen and the screensaver silence it, and the sound comes back after.
- While VECTOR speaks or a codec call plays, it ducks to `[tv] duck`, 30% by default.
- A small speaker on the screen says the sound is on.

### Commands

```bash
bromigos-live tv list                       # every screen's channels; * marks the one on
bromigos-live tv set 2 --screen big         # channel 2 on the big monitor
bromigos-live tv next --screen scope        # the next channel (prev: the previous)
bromigos-live tv open                       # full screen with sound
bromigos-live tv close                      # back to the den: close full screen
bromigos-live tv live                       # back to the channel after something played on demand
bromigos-live tv web                        # what's on, in the server's or YouTube's web page
bromigos-live tv guide                      # the channel guide (the Den TV app)
bromigos-live tv sound on --screen small    # on, off or toggle; on one screen at a time
bromigos-live tv volume up                  # up, down, or a level: volume 40
bromigos-live tv state --json               # what's on each screen, the sound, what mpv is doing
bromigos-live tv poster --screen big --json # what's on as a small JPEG, base64
```

`volume`, `sound`, `close`, `live` and `poster` take `--json`, as `remote`, `set`, `play`
and `channels` do: one JSON object, `"ok": true` with the result, or `"ok": false` with
`error` and a non-zero exit. Remotes use them: BRODEC's den remote calls them through the
machine agent. `poster` fetches the picture through the media server's adapter, so its
address and key never leave it.

`--screen` takes `big`, `wave` or `emblem`, and `scope` and `small` too. Without it, a
command acts on the screen under the pointer, as the keys do. `bromigos-live tv help` has
the details.

### The channel guide

The channel guide is the standalone **Den TV** app (`bromigos-tv-guide`)
([docs/settings.md](../docs/settings.md#den-tv)). Settings has playback controls and an open button. The guide opens from
`bromigos-live tv guide`, from Super+Alt+G, from the hint's **GUIDE** and from the MEDIA
panel's settings.

![The channel guide: every channel as a card, each with its poster, what's on now and next, a
progress bar, its source and order, and a lit button for each screen it's on air on](../docs/images/den-tv-guide.webp)

- **What it shows.** Every channel once, channel 1 (each screen's own picture) first. Each
  card has what's on now and next, the item's poster, a progress bar, the channel's source
  and its order. Under it, **BIG**, **SCOPE** and **SMALL** tune that screen to it. The
  button of each screen on air there is lit, and the card says **ON AIR**.
- **What it changes.** Add channel (a library, collection or playlist the servers list,
  shows or movies you pick from a searchable grid of posters, a YouTube address, a folder,
  or your downloaded YouTube videos), and for each card: Rename, Contents (view, add, remove and reorder picks), Pick shows, Move earlier
  or later, Bumpers, the screens it's on (every screen unless you say), and Remove, with
  confirmation and Undo. Media files stay. Drag a card onto another to put it before that one.
- **Keys.** Tab moves between cards. On a card, 1, 2 and 3 tune the big monitor, the scope
  and the small monitor. Delete removes, F2 renames, and Alt and an arrow move it.
- **The file.** It writes the `[[tv.channel]]` tables of
  `~/.config/bromigos-live/config.toml` in place through `lib/bromigos_tvchannels.py` and `lib/bromigos_tvconfig.py`. Comments,
  blank lines and every other table stay as they were, and a channel's own comments move
  with it. Each save is checked first, then written in one step to the file a symlink
  points at, so a dotfiles link stays a link. The live layer notices a change that only
  touches the channels and reads them again without rebuilding the den, so nothing
  restarts.

### Shared channel commands

`bromigos-live tv channels --json` lists configured channels, contents, order, bumpers,
screens and now/next from the cache. `--refresh` reads contents from the servers.
`bromigos-live tv channel --help` lists create, rename, order, bumpers, move,
add-item, remove-item, move-item, tune, remove and undo. Each takes `--json`.
`remove` requires confirmation or `--yes`; it removes no media files.
The [media guide](../manual/src/media.md#make-channels-for-the-den-tv) has examples.

Channel identifiers are names or one-based config positions. Screen channel numbers
include its own picture and any extra live stream. Use `channel tune NAME --screen S`
when starting from a channel name. All writes share `bromigos_tvchannels.Store` with the
GTK guide, media TUI and VECTOR. A lock around the read/edit/write prevents the interfaces
from overwriting each other's newer changes. The content cache records the channel definition. Changed picks or sources refresh
immediately rather than waiting for the regular cache age. A failed refresh never keeps
items from a different definition. An empty schedule stops the previous item's picture
and sound while the new list loads. Channel deletion keeps a recoverable table
in user state for `channel undo`.

Picked `items` may include YouTube URLs or `music:artist:NAME` / `music:album:NAME`.
YouTube picks use the existing resolver and cache; music comes from Jellyfin or Plex and
plays through the TV's sound controls. Titles not yet on the server remain picks and
show a missing-title message until available.

### Tests

| Test | What it checks |
|---|---|
| `tests/test_tv.py` | The schedule, the channels, the remembered state, YouTube against a stand-in for yt-dlp (`tests/fake_ytdlp.py`) and keeping videos |
| `tests/test_tv_screens.py` | Every screen at once, `[tv.start]`, one player for two screens on a channel, bumpers, `max_playing`, the sound on one screen, `--screen`, covering and opacity, the hint's speaker, streams sized to each screen from stand-in Jellyfin and Plex servers (`tests/fake_media.py`), YouTube resolved while yt-dlp is slow and the screen is covered and uncovered, picked shows shuffled and taking turns, and the config writer keeping comments |
| `tests/offscreen_tv.py` | The den pixel for pixel as before with no media channel on, a generated test clip playing through libmpv in two themes, the hint, the poster with still motion, three screens playing at once, one channel on two screens from one player, a bumper card, and a tune that never leaves the last channel's picture. `OFF_MEASURE=20` measures the cost |
| `../homelab/tests/test_video.py` | The Jellyfin and Plex adapters against fake servers |
| `../desktop/tests/test_den_tv_guide.py` | The channel guide, Add channel and the show picker, drawn in a headless weston, and every control's hover hint |
| `../desktop/tests/e2e_tv_nested.py` | The whole thing in a nested Hyprland, with a fake Jellyfin and a PipeWire nobody hears: three screens playing, the sound moving, and the channel guide driven (`den_tv_guide_driver.py`) with the live layer following |

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
| `live/tv.py`, `live/mpvgl.py` | The den TV: its channels on the den's screens, the hint, sound and full screen; libmpv drawing into a texture |
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
| `~/.local/state/bromigos-live/` | `live.log`, the 72-hour history (`history.npz`, `events.jsonl`), `swarm-seen.json`, the `muted` and `codec-quiet` flags, the den TV's `tv.json` |
| `~/.cache/bromigos/tv/` | The den TV's channel lists, what the servers offer, files' lengths, and items that wouldn't play |
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

## Den TV controls

The den screens have a hover menu for channels, sound, volume, skip, full screen and the guide.
The hover menu is on by default and uses `tv.hover_hint`.
`bromigos-live tv hint on|off` changes it.
Skip advances the channel's saved clock, so switching away and back keeps its
progress. All screens tuned to that channel share it. The clock is stored in
`$XDG_STATE_HOME/bromigos-live/tv-clocks.json` (default `~/.local/state/`).
The MEDIA widget has a rotary dial and per-screen sound controls. Full-screen playback
loads only the den's own `live/tvosc.lua`, with a private palette and IPC connection;
it leaves global mpv settings alone. The number-pad remote selects a screen with
Super+KP 1/2/3 and releases it with Super+KP 0, Escape or a fifteen-second timeout.

`lib/bromigos_tvplay.py` shares media search and on-demand playback between the Den TV
app, media TUI, CLI and VECTOR. `lib/bromigos_tvremote.py` shares hint, selection and
remote commands. The media TUI uses `p` to play on a den screen and `P` for a profile.

The package's check dependencies include PyOpenGL, Cairo, Pillow, GTK3, mpv and ffmpeg.
That runs the fake-player control tests and the private controller's real `--vo=null`
tests in the build container. A minimal source checkout skips those tests when their
runtime is absent; it still runs the shared search and config-writer checks.

The null-player tests wait for mpv and its IPC worker to exit before removing their
sandbox, so palette polling cannot race directory cleanup.

Muting shows a crossed-out speaker on the TV for the feedback interval, even if the
volume bar is still visible. The hover menu, keys, CLI, VECTOR and MEDIA knob use
the same path.

## Game mode

The session's transient game marker pauses background frames and TV playback without
changing saved wallpaper settings. Notification overlays, sound cues and new codec
calls stay quiet too. Removing it restores the usual coverage and playback
rules. See [game mode](../docs/desktop.md#game-mode).
