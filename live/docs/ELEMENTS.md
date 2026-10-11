# Every element of the live background

This is the catalogue of everything the live layer draws on the background, and its
event animations. For each element it says what it looks like, what it shows, where its
data comes from, the code and config behind it, what it costs and how to change it. The
last sections explain how to add an element, with two worked examples.

The live layer is the program that draws bromigOS's animated background
([../README.md](../README.md)). With the default theme, the Wick, the background is *the
den*: a painted radio room whose screens, meters and floor the live layer brings to life.

## The rule

Anything that moves shows a real reading or a real event. The exceptions are marked
*decoration*: the emblem, the stars and the seamless loops. Decoration moves at a fixed,
calm pace and is tied to nothing.

## Before you start

- **Coordinates** are pixels in the 2560×1440 den plate, with the origin at the top left.
  The code scales them to the monitor: `sx = w / 2560`, `sy = h / 1440`.
- **Paths** are relative to `live/` in this repository. The package installs the code in
  `/usr/lib/bromigos/live/`.
- **Config.** The default is `/usr/share/bromigos/live/config.toml`. A user's
  `~/.config/bromigos-live/config.toml` is merged over it, key by key. The config reloads
  when saved. Code changes need `bromigos-live restart`.
- **Reduced motion.** Every element follows the user's motion setting: `full`, `reduced`
  or `still` ([docs/accessibility.md](../../docs/accessibility.md) has the table of what
  each mode does). A new element must follow it too:
  - animate on the renderer's scene clock (`self.clock`, from `live/motion.py`), not raw
    time, so it slows and stops with the rest;
  - gate anything that flashes, blinks, flickers or turns on `self.calm` in Python, or
    `u_calm` in a shader;
  - under `still`, let a changed reading show through the scene's `picture()`.

## At a glance

| Element | Where | Shows | Config key |
|---|---|---|---|
| [Oscilloscope](#oscilloscope) | The den's small scope | Network throughput, last 48 s | `background.den` |
| [Relay map](#relay-map) | The den's big monitor | The homelab's nodes and links | `background.den` |
| [Emblem monitor](#emblem-monitor) | The den monitor left of the desk | The burn-in turning (decoration) | `background.den` |
| [Meters](#meters) | Two analog meters on the desk | CPU load and GPU load | `background.den` |
| [The den TV](#the-den-tv) | Any of the three screens above | Your own videos as TV channels, on the clock | `[tv]` |
| [Glyph rain and bursts](#glyph-rain-and-bursts) | The dark sky at the top | CPU load, and bursts for events | `[rain]` |
| [Floor pulses](#floor-pulses) | The den's floor grid | Download and upload | `[floor]` |
| [Ships and debris](#ships-and-debris) | The open sky and the den's window | Network throughput as traffic | `space.traffic` |
| [Stars](#stars) | The dark sky | Decoration | `space.stars` |
| [Relay beam](#relay-beam) | From the station, up and left | The homelab is all green | `space.relay_beam` |
| [Health tint](#health-tint) | The sky and the rain | Running hot, or the homelab in trouble | `space.health_tint` |
| [X-ray sweep](#x-ray-sweep) | A beam across the screen | This machine's parts and readings | `[sweep]` |
| [Workspace wipe](#workspace-wipe) | A line down the screen | A workspace change | `events.workspace_wipe` |
| [Intercept](#intercept) | Full screen, once | A login or an unlock | `events.intercept_on_*` |
| [Transmission](#transmission) | Around the notification | A critical notification | `events.critical_flash` |
| [Codec calls](#codec-calls) | A card, bottom right | Notable events, spoken | `[codec]` |
| [Screensaver](#screensaver-planet-and-station) | Full screen when idle | The local hour, the homelab, the clock | `[screensaver]` |
| [Loops](#loops-steam-streaks-rows) | The mug, the left edge, the floor | Decoration | `[loops]` |
| [Plugin shader layers](#plugin-shader-layers) | Anywhere behind windows | Whatever the layer reads | `layers/<name>.json` |
| [Sound cues](#sound-cues) | Audio | Terminals, notifications, the intercept | `[sounds]` |
| [Worlds](#worlds) | The whole background | Everything, as a living scene | `[world]` |

The decks and the radial menu aren't part of the background. They're overlays you open.
[../README.md](../README.md#decks) describes them.

## How the background is drawn

The background is one GTK window on the layer-shell BACKGROUND layer, behind every
window, with one GL context. Each frame, `Background.render()` in `live/scene.py`:

1. reads the latest snapshot from `live/data.py` (`Data.snapshot()`). The data loops run
   on their own threads, so a frame never waits for a reading.
2. draws the glowing gadgets, such as the relay map, into an offscreen target and blooms
   them.
3. runs one full-screen shader, `shaders/bg.frag`, with every reading passed in as a
   uniform. It includes `rain.glsl` (the palette, glyphs and rain), `space.glsl` (stars,
   ships, beam, tint and planet) and `denloop.glsl` (the loops).
4. draws any plugin shader layers on top (`live/plugins.py`).

### Frame rates

| When | Frame rate |
|---|---|
| The desktop is visible | 30 fps |
| Windows are tiled over it | 20 fps |
| Locked, under a fullscreen window, or under a deck | 0 fps |

`App.refresh_state()` in `live/app.py` sets the rate. The data loops slow down three to
four times while the background is paused. Measured, the daemon uses 7–9% of one CPU
core and under 1% of the GPU.

### When the background is missing

`bromigos-live status` says why the background isn't showing:

| Status | Meaning | What happens |
|---|---|---|
| `background off (toggled off: …)` | The user turned it off with Super+Shift+B | It stays off, even across config reloads |
| `background off (config: …)` | `background.enabled = false` | It stays off until the config changes |
| `surface=FAILED` | The window couldn't be created | `App.heal()` retries after 30 s, 60 s, 2 min, then every 5 min |
| `surface=MISSING` | The compositor dropped the window | It's rebuilt on hotplug, unlock, display-on and every 30 s |
| `waiting for the output` | The monitor is gone | The window comes back with the monitor |

At start, `wait_for_display()` in `live/app.py` waits up to 60 seconds for a Wayland
display with a monitor. Without one, the daemon exits with code 3. The supervisor
starts it again, or stops when no Wayland session is left.

### Where each layer may draw

- **The dark sky** is the painting's deep space: `u_space_rect`, from x 0 to 2400 and
  from y 34 down to the floor's horizon. Layers draw only on dark pixels, where the
  painting's luminance is under about 0.1 (`lum_mask` in the shader). So nothing paints
  over the art.
- **The den's screens** are the rectangles in `DEN` in `live/scene.py`, fitted by hand to
  the approved den images.
- **The floor** is below `floor.horizon_y` and left of `floor.max_x`.

## Elements

### Oscilloscope

- **Looks like:** a green trace on the den's small scope. It's a carrier wave whose
  height swells and falls, over a faint grid. Rectangle `DEN["wave"]` = (1475, 762, 124,
  110).
- **Shows:** this machine's network throughput, download plus upload, over the last 48
  seconds. The newest reading is on the right. The height is log10(1 + bytes/s) / 7. The
  wave's wiggle is decoration; its envelope is the data.
- **Data:** `psutil.net_io_counters`, every second, in `Data._local_loop` (`rx_hist`,
  `tx_hist`, 48 samples). Loopback, Docker, bridge and VPN interfaces are skipped.
- **Code:** `Background.render()` builds `self.wave`. The drawing is the first block of
  `den()` in `bg.frag`. Uniforms: `u_wave_rect`, `u_wave[48]`.
- **Config:** `background.den`, which switches all four den screens together.
- **Cost:** negligible. A few operations per pixel, inside the rectangle only.
- **Change it:** the height scale is the `/ 7.0` in `render()`. The wave's shape is
  `carrier` in `den()`.

### Relay map

- **Looks like:** a small turning constellation on the den's big monitor. The homelab's
  nodes are dots with ring markers, joined by links with packets running along them.
  Rectangle `DEN["big"]` = (1188, 678, 200, 175).
- **Shows:** the homelab's nodes, coloured by health: phosphor for ready, amber for
  degraded, red for down, grey for no readings. Packets on each link scale with the far
  node's CPU. The uplink follows internet throughput, and the AI link follows model
  requests per minute.
- **Data:** the homelab's snapshot from `bromigos-homelab`, every 25 seconds
  (`Data._cluster_loop`; `cluster.poll_seconds`, never under 20).
- **Code:** `gadgets.constellation(..., mini=True, labels=False)`, called from
  `Background.rebuild()`, which rebuilds the geometry every 2 seconds. It turns at 0.25
  rad/s (`p.rot[1]`, `p.ctr[1]` in `render()`). The glass behind it is in `den()` in
  `bg.frag`.
- **Config:** `background.den`.
- **Cost:** about a hundred instanced primitives, rebuilt twice a second.
- **Change it:** `gadgets.constellation` is shared with the holo deck and the
  screensaver. `NODES`, `LINKS` and `WAN` at the top of `gadgets.py` place things.

### Emblem monitor

- **Looks like:** the burn-in, the Bromigos emblem of a flame in a ring, on the den
  monitor left of the desk. The ring turns anticlockwise, with faint phosphor noise and a
  short burst of static every 17 seconds. Rectangle `DEN["emblem"]` = (1090, 920, 158,
  143).
- **Shows:** decoration. The emblem is the one element allowed to move for its own sake.
- **Code:** the second block of `den()` in `bg.frag`. The textures `u_ring` and
  `u_flame` come from `Emblem` in `live/emblem.py`, drawn from the canonical SVG. The
  uniform `u_den` turns it once every 24 seconds.
- **Config:** `background.den`.
- **Change it:** the turn rate is the `24.0` in `u_den`. Never redraw the emblem by hand.
  It comes from `lib/bromigos_emblem.py` in the `bromigos-core` package.

### The den TV

- **Looks like:** a TV picture in one of the den's screens, in the screen's glass: the
  tube's curve, scanlines, a soft glow, and the den's phosphor tinting it. Changing
  channel gives a burst of static and the channel number. A small speaker in the corner
  means the sound is on.
- **Shows:** a TV channel from your own library: Jellyfin, Plex, YouTube or a folder. What
  plays comes from the wall clock, so it's real, not decoration. Channel 1 is the screen's
  own element. The scene stays unchanged when Den TV is disabled.
- **Data:** the channel's list, read by a thread and cached (`lib/bromigos_tv.py`); the
  picture from libmpv's render API (`live/mpvgl.py`), decoded on the GPU, one player per
  screen showing a media channel.
- **Controls:** `live/tvcontrol.py` draws the equipment's knobs, buttons and standby
  lamp from each screen's rectangle. Tiny readouts last only while the pointer is over
  a knob, including when the pointer leaves for another window. `tv.hover_hint` controls
  the floating panel independently. The same action path serves keys, CLI and VECTOR.
- **Code:** `live/tv.py`. `Background.render()` asks `tv.gl()` for each screen's uniforms
  and draws the hint after the frame (`_draw_hint`). In `bg.frag`, `tv_picture()` and
  `tv_osd()`, called in `den()` for each screen with its own uniforms and textures:
  `u_tv_wave`, `u_tv_emb`, `u_tv_big`, `u_tune_*`, `u_tvtex_*` and `u_osd_*`.
  `Background.rebuild()` leaves the relay map off the big monitor while a channel plays
  there.
- **Config:** `[tv]` and `[[tv.channel]]` ([../README.md](../README.md#the-den-tv)).
- **Cost:** see [../README.md](../README.md#the-den-tv). Nothing is decoded while a
  screen isn't in view, or while a window covers a muted one.

### Meters

- **Looks like:** two analog panel meters on the desk, each with a scale arc, ticks, a
  red zone and a needle. Their face colour is sampled from the painting, so the live
  faces match it. `DEN["meter0"]` = (1545, 932, 66, 32) on the left and `DEN["meter1"]` =
  (1555, 1050, 61, 32) on the right.
- **Shows:** CPU load on the left, across all cores, and GPU use on the right. Each runs
  from 0 to 100% across ±0.6 rad.
- **Data:** CPU from `psutil.cpu_percent` every second (`Data._local_loop`, key `cpu`).
  GPU from `nvidia-smi -lms 1500` (`Data._gpu_loop`, key `gpu`). The needles ease toward
  the value in about a quarter of a second (`meter_v`).
- **Code:** the `for i, k in enumerate(("cpu", "gpu"))` loop in `Background.render()`,
  and the meter loop in `den()` in `bg.frag`. Uniforms: `u_meter0`, `u_meter1`,
  `u_meter_v`, `u_meter_face`.
- **Config:** `background.den`.
- **Change it:** see the [worked example](#change-what-an-element-shows-the-left-meter-shows-ram)
  that makes the left meter show memory.

### Glyph rain and bursts

- **Looks like:** columns of glyphs falling through the dark sky, with bright heads,
  fading tails and glyphs that change as they fall. The glyphs are the Drift script, an
  original set of 24 built from relay-mast strokes. A burst is a ripple that runs
  sideways from one column, brightening and recolouring the rain for about 2.6 seconds.
- **Shows:** CPU load sets the rain's density, 0.22 + 0.55·min(1.6·cpu, 1), and its
  speed, 0.55 + 1.6·cpu. Bursts show events:
  - a notification, in soft green;
  - a critical notification or a homelab alert, in red;
  - a fill from the trade feed, in amber.
- **Data:** CPU as above. Notification bursts come from `App.on_notify`. Homelab alerts
  (`cluster_alert`) and fills come from `App.on_data_event`.
- **Code:** `rain()` in `shaders/rain.glsl`, shared with the overlays.
  `Background.burst(kind, x, strength)` fills one of six slots (`u_burst[6]`: x, start
  time, strength, colour). Uniforms: `u_rain_rect`, `u_rain`.
- **Config:** `[rain]`: `enabled`, `region` (x, y, w, h; default 0, 30, 2390, 600),
  `brightness`, `bursts`.
- **Cost:** two glyph tests per 15×24 cell, only inside the region and on dark pixels.
- **Change it:** a new burst source is one `self.bg.renderer.burst(kind)` call where the
  event arrives in `app.py`. A new colour goes in `burst_col()`.

### Floor pulses

- **Looks like:** pulses of light running along the den floor's converging lanes.
  Phosphor pulses run toward you, and amber ones run away toward the horizon, each with
  a soft tail.
- **Shows:** this machine's network throughput. Pulses toward you are downloads, and
  pulses away are uploads. The share of lanes carrying a pulse, and their speed, follow
  log10(1 + bytes/s) / 7.5.
- **Data:** `rx` and `tx` from psutil, every second.
- **Code:** `floor_pulses()` in `bg.frag`. Uniforms: `u_floor` (horizon y, vanishing x,
  lane slope, lane offset), `u_floor2` (max x, draw own grid, on), `u_net`.
- **Config:** `[floor]`: `enabled`, and the fit `horizon_y = 926`, `vanish_x = 690`,
  `lane_slope = 0.98`, `lane_offset = 0.71`, `max_x = 1000`. `draw_grid` draws a grid
  when the painting has none to ride on.
- **Cost:** a short loop over two directions per floor pixel.
- **Change it:** the fit must match the painting's own lanes. Change it only with an
  offscreen render to compare (`tools/offscreen.py bg out.png`).

### Ships and debris

- **Looks like:** small wireframe haulers crossing the sky on straight paths, plus
  tumbling flecks of debris. Each ship has amber engines, a trail behind it and a red
  navigation light. They fly at many headings: level, gentle diagonals of 10–35°, and a
  few steep ones of 50–70°, either way. They fly at three depths:

  | Depth | Size | Speed | Brightness |
  |---|---|---|---|
  | Far | 0.5× | 7–13 px/s | Dim |
  | Mid | 0.8× | 14–26 px/s | Medium |
  | Near | 1.15× | 24–38 px/s | Bright |

  Near ships hide far ones where they overlap. Now and then a far ship approaches or
  recedes, changing size along its path.
- **Where:** in both of the den's skies. That's the open sky left of its wall, and the
  space seen through its window on the right. Paths are planned across the whole sky and
  aimed through each region in turn (`shipmask.FOCUS`). So a ship can slip behind the
  wall and reappear in the window. Two masks, multiplied together, decide where a ship
  shows:
  - `live/shipmask.py`, fitted to the den plate. It allows the open sky left of x 995,
    fading out over the 40 pixels above the horizon, and the window's glass. Ships never
    show over the den's screens, frame or interior. The shader samples it as
    `u_shipmask` in `traffic()`.
  - the dark-pixel test every sky layer uses. So the station, the wrecks and anything
    else bright in the painting hide the ships behind them.

  On any other wallpaper, only the dark-pixel test applies.
- **Shows:** network throughput, as traffic. Whether a crossing carries a ship is
  decided once, before it enters the screen. It's busy if a stable random draw is under
  0.12 + 0.88·level, where level = log10(1 + rx + tx) / 7.3 (`gadgets.traffic_level`).
  The whole path is fixed then, so a ship never appears or vanishes mid-screen. The
  number of busy lanes follows the level, at most one crossing behind. Debris density
  follows a 25-second average of the level, and flecks fade in and out rather than
  blink.
- **Data:** psutil, every second.
- **Code:** `live/traffic.py` has ten lanes (`TIERS`: three far, five mid, two near).
  `Traffic.uniforms(level, rect)` plans each crossing with `heading()` and `path()`,
  works out every position in double precision, and returns them sorted far to near.
  `traffic()`, `ship_dist()` and `ship_cover()` in `shaders/space.glsl` draw them from
  `u_ship[10]` (x, y, heading, scale), `u_ship2[10]` (brightness, occupied, hull kind) and
  `u_ship_rect`. `u_space.y` is the smoothed level, or −1 when off. The background and
  the screensaver each own a `Traffic`.
- **Config:** `space.traffic`.
- **Cost:** with all ten lanes busy, the median background frame took 1.03 ms, against
  0.95 ms with traffic off, on an RTX 5070. Each pixel skips any ship more than 150
  pixels away.
- **Change it:** tiers, speeds and brightness are in `TIER`. The mix of headings is in
  `heading()`, the busy rule in `_new()`, the hull in `ship_dist()` and its silhouette in
  `ship_cover()`. Never decide occupancy in the shader from the live level: that made
  ships pop in and out. These aren't the Swarm deck's ships (`live/starship.py`).

### Stars

- **Looks like:** three layers of twinkling stars, drifting slowly at different speeds.
- **Shows:** decoration.
- **Code:** `stars()` in `space.glsl`. Uniform: `u_space.x`.
- **Config:** `space.stars`.

### Relay beam

- **Looks like:** a thin beam rising up and to the left from a point at (2000, 370) in
  the right of the sky. Three pulses run out along it, fading with distance.
- **Shows:** that the homelab is all green: the last read of its snapshot worked, every
  node is Ready and every service is up (`gadgets.all_green`). Otherwise there's no beam. This machine
  running hot doesn't turn it off; that only tints the sky amber. The pulse speed is
  0.12 + min(ingress requests/s, 6) / 12, so a busier ingress pulses faster.
- **Data:** the homelab's snapshot, every 25 seconds: `cluster.nodesReady`,
  `nodesTotal`, `services[*].status` and `traefik.rpsNow`.
- **Code:** `relay_beam()` in `space.glsl`. Uniforms `u_space.z` (on) and `u_beam` (x0,
  y0, angle, pulse speed), set in `Background.render()`. The screensaver draws the same
  beam from its station. The Drift map has its own beam with the same meaning.
- **Config:** `space.relay_beam`.
- **Change it:** the origin and angle are `bx0, by0` and `-2.5` rad in `render()`.

### Health tint

- **Looks like:** the whole sky layer, with its stars, ships and beam, and the rain shift
  toward amber or red. The den's screens and floor keep their colour.
- **Shows:** a health level, from `gadgets.health`:
  - 0: all well.
  - 1, amber: the CPU is at 90 °C or more, the GPU at 87 °C or more, or the last read
    of the homelab's snapshot failed.
  - 2, red: a homelab node isn't Ready, or a homelab service is down.
- **Data:** temperatures from psutil every 5 seconds, `nvidia-smi`, and the homelab's
  snapshot.
- **Code:** `health_tint()` in `space.glsl`. Uniform: `u_space.w`.
- **Config:** `space.health_tint`.

### X-ray sweep

- **Looks like:** a phosphor beam crossing the screen left to right in about 5.5
  seconds. Behind it, for about half a second, an X-ray schematic of this machine shows
  over the den, darkening the painting under its lines. Rectangle `DEN["schem"]` = (1000,
  560, 860, 660). Super+X pins the schematic. Holding Super+Z keeps it up while held.
- **Shows:** this machine's real parts, such as the CPU, GPU, memory, drives and board,
  labelled with their readings at the moment of the pass. The beam itself is decoration.
- **Data:** the snapshot, drawn with Cairo just before each pass (`draw()` in
  `live/schematic.py`), and every 2 seconds while pinned or held.
- **Code:** the sweep's schedule is in `Background.render()`, the drawing in
  `_draw_schematic()`, and the reveal in `main()` in `bg.frag`. Uniforms: `u_sweep`,
  `u_scan`, `u_scan2`, `u_schem_rect`, and the texture `u_schem`. On demand:
  `bromigos-live scan`, `scan-pin` and `scan-hold on|off`.
- **Config:** `[sweep]`: `enabled`, `interval = 60` (seconds between passes), `duration
  = 5.5`.
- **Cost:** one texture upload per pass, 860×660. Otherwise a few operations per pixel.

### Workspace wipe

- **Looks like:** one soft line sweeping down the screen in 0.45 seconds, with a faint
  glow behind it.
- **Shows:** a workspace change, from Hyprland's `workspacev2` event (`App.on_hypr`).
- **Code:** `Background.wipe()`, and `main()` in `bg.frag`. Uniform: `u_wipe`.
- **Config:** `events.workspace_wipe`.

### Intercept

- **Looks like:** a full-screen overlay. The frozen screen holds, then tears. The
  burn-in's ring draws itself, the flame lights and the ring turns. "TRANSMISSION
  INTERCEPTED" and a sign-off type themselves out, then a ghost of it fades. It takes
  about 4 seconds, plus a 3-second ghost that never takes input.
- **Shows:** a login, from `bromigos-live start --login` in Hyprland's autostart, or an
  unlock, from the daemon's lock watcher (`live/watch.py`).
- **Code:** `Intercept` in `live/overlays.py`. The timings are `HOLD`, `TEAR`, `RING`
  and `FLAME`; the text is `CAPTION` and `SIGN`. The sound cues are `hiss` and
  `signoff`.
- **Config:** `events.intercept_on_login`, `events.intercept_on_unlock`.
- **Rules:** it follows the canonical burn-in sequence. Under reduced motion, crossfades
  replace the tear, the turn and the black frame. Under `still`, the finished card fades
  in and out.

### Transmission

- **Looks like:** targeting brackets that snap around the notification popup, a 150 ms
  band of interference, a red pulse at the edges, and a ghost when it's dismissed.
- **Shows:** a critical notification, with urgency 2 on D-Bus. Never while locked.
- **Code:** `Transmission` in `live/overlays.py`. `notification_rect()` finds the popup.
  `App.on_notify` triggers it.
- **Config:** `events.critical_flash`. The sound cue is `sounds.critical`.

### Codec calls

- **Looks like:** a compact card in the bottom-right corner. It has a channel glyph, a
  tuning dial with the channel's name, the voice's real loudness as a waveform, and the
  message typing out in step with the voice. The channels are CH 01 THE FLOOR, CH 02 THE
  LAB, CH 03 THE DECK and CH 04 PRIORITY.
- **Shows:** notable real events, spoken in VECTOR's voice:
  - notable fills from the trade feed, over `fill_min_realized` or `fill_min_notional`;
  - homelab alerts, while VECTOR's own daemon is down. When it's up, he briefs them
    himself;
  - long commands run with `bromigos-live job -- <command>`;
  - critical notifications;
  - anything sent with `bromigos-live codec "text" CHANNEL`.
- **Code:** `live/codec.py` has the queue, rate limits and voices (`Desk`, `Call`).
  `live/codec_panel.py` draws the card (`CodecPanel`).
- **Config:** `[codec]`:
  - `enabled`;
  - `voice`: `"pilot"` uses VECTOR's voice server, and `"breeze"` skips it for the
    fallback text-to-speech;
  - `min_gap = 120`, `max_per_hour = 8` and `dedupe = 1800`, all in seconds or calls;
  - `on_critical`, `on_lab_alert`, `on_fill` and `job_min_seconds`.

  Super+Shift+M mutes everything. Super+Shift+C makes calls silent.
- **Rules:** one call at a time. Never while locked or under a fullscreen window.

### Screensaver: planet and station

- **Looks like:** a wireframe gas giant rising from the bottom right, the Drift relay
  station top left with its spokes, the homelab's constellation, this machine's arc
  rings, the burn-in turning, rain over the whole screen, and the time and date in the
  middle. Any key, click or real mouse movement ends it.
- **When:** the idle policy starts it, after 8 minutes by default. By default that's
  before the lock at 10 minutes. With the "Screensaver only" preset, nothing locks after
  it. Users set this in Settings › Idle & lock or `~/.config/bromigos/idle.toml`
  ([docs/idle.md](../../docs/idle.md)).
- **Shows:**
  - the planet's terminator is the local hour, facing you at noon and away at midnight
    (`gadgets.local_sun_angle`);
  - the station's spokes are the homelab's services, lit when up;
  - the rings are this machine's load;
  - the relay beam runs from the station when the homelab is all green;
  - a "DEGRADED" or "RUNNING HOT" line appears at health 2 or 1.
- **Code:** `Screensaver` in `live/overlays.py` (`build()`, `frame()`), with
  `gadgets.drift_station`, `gadgets.rings` and `gadgets.constellation`. The planet is
  `planet()` in `space.glsl`, with uniforms `u_planet` and `u_sun`.
- **Config:** `[screensaver] enabled`, `space.planet`, `space.station`.

### Loops: steam, streaks, rows

- **Looks like:** steam curling up from the mug, glitch streaks drifting, stretching and
  fading on the left edge, and the floor grid's rows scrolling toward you.
- **Shows:** decoration. They move at a constant pace, tied to nothing.
- **Code:** `shaders/denloop.glsl` (`den_steam`, `den_streaks`, `den_rows`,
  `den_loops`). The phases come from `Background.loop_uniforms()` (`u_loop`). Each phase
  is computed in double precision on the CPU and wrapped by its own period, so every
  loop closes exactly. The steam and streaks painted into the den are removed in memory
  by `clean_plate()` in `live/plate.py`. The wallpaper file is never changed.
- **Config:** `[loops]`: `streaks`, `streak_period = 10`, `rows`, `row_period = 12`,
  `row_amp`, `steam` (the den variants whose mug steams), `steam_period = 7`,
  `steam_intensity`.
- **Rules:** a loop must close without a seam. Check by rendering frames on both sides of
  the wrap.

### Plugin shader layers

- **Looks like:** whatever the layer draws, over the finished background and behind
  every window.
- **Shows:** a real reading, or the slow ambience the rules allow. The contract gives a
  layer `u_load` (CPU, GPU, memory, video memory), `u_net` and `u_health`.
- **Code:** a layer is `layers/<name>.frag` plus `layers/<name>.json`, loaded by
  `Layers` in `live/plugins.py`. Layers are opt-in (`"enabled": true`). Each layer's GPU
  time is measured. It switches itself off when it goes over `budget_ms`, or if its
  shader fails to compile.
- **How:** [docs/plugins.md](../../docs/plugins.md), and VECTOR's `live-shader-layer`
  skill in the vector repository's `skills/`.

### Sound cues

`live/sound.py` plays `sounds/*.wav` through PipeWire, at `sounds.volume` (0.3 by
default):

- a blip when a terminal opens (`terminal_classes`);
- a chirp for a notification, except from `quiet_apps` or with a `capture.` category;
- an alert for a critical notification;
- the hiss and sign-off in the intercept;
- a sweep when a ship warps into the Swarm deck.

Super+Shift+M mutes the theme's sounds and VECTOR's voice together. `sounds.sink`, or
`BROMIGOS_LIVE_SINK`, sends the cues to another PipeWire sink. To test, use a null sink,
never the speakers.

## Worlds

A *world* is a theme whose background is a living scene instead of the den. When the
current theme has `live/world.toml`, the live layer draws that world: layered art with
parallax, a water plane, effects and actors, every moving thing tied to a real signal.
The Wick has no world, so it keeps the den. `bromigos theme set mire` switches to a
world, and `bromigos theme set wick` switches back.

The world format is documented in [docs/theming.md](../../docs/theming.md), and what each
thing in each world shows is in [docs/worlds.md](../../docs/worlds.md). This section
explains how the live layer runs a world.

### Loading

`world_file()` in `live/world.py` looks for the world in this order:

1. `$BROMIGOS_WORLD`;
2. `[world] dir` in the config;
3. `~/.local/state/bromigos/theme/current/live/world.toml`, which `bromigos theme set`
   copies there before it tells the live layer.

`App.check_world()` also checks the file's signature every 3 seconds, and rebuilds the
background when it changes. A world that fails to load falls back to the den, and the
log says why.

### Drawing a frame

`World.render()` draws each frame:

1. the hour's light, and any lightning;
2. every layer and actor above the water, into a back target;
3. `shaders/world.frag` composes the frame from it. The water is either a mirror that
   reflects the back target with ripples, rain rings and wakes, or a split view with a
   moving surface, fog and caustics. Then come mist, fireflies and their reflections,
   the fishing line, the lighthouse beam, spray and rain;
4. the deeper layers and actors over that.

Layers use `world_layer.frag`. The sky layer also carries the real moon, the twilight
glow and lightning bolts. Actors are instanced sprites from one atlas
(`world_sprite.*`), plus additive lights (`world_glow.*`).

### Actors

`live/actors.py` has the kinds of actor: `keeper`, `agents`, `signal`, `crowd`,
`traffic` and `event`. They share their motions, and the "needs you" gesture where an
actor turns and signals. Positions are planned on the CPU in plate pixels, as with the
ships, so nothing pops in or out.

### Data

A world reads everything the den does: CPU, network, homelab health, the trade feed's
fills and notifications. While a world is showing, it also reads:

- **coding agents**, from herdr, a terminal workspace manager for AI coding agents
  (`live/worldfeed.py`, every 2 seconds, or 8 while paused);
- **VECTOR's state**, from his state file (checked every 0.5 seconds);
- **your activity**, from `live/activity.py`: working, dozing or asleep. The idle
  policy's `[activity]` timer tells hypridle to send `ctl activity idle|active` after 90
  seconds ([docs/idle.md](../../docs/idle.md)). Until hypridle has read that, the live
  layer watches the pointer (through Hyprland, twice a second), focus and workspace
  events, and the lock;
- **the sky**, from `live/skyclock.py`: the hour's light, the moon's phase and place,
  and the tide, all worked out locally.

An effect or actor with `requires` names a signal it needs, such as `"lab"`. It isn't
drawn while that source is unavailable. Without a homelab, Mire's mast light and
Tidewell's beam stay dark.

### Camera

The layers sway with the pointer while you work, for parallax, and settle back when
you're idle.

### Video loops

A layer's `video`, or any actor sprite that names a video file, plays it as a GPU
texture (`live/videoloop.py`, `shaders/world_yuv.frag`):

- Each loop runs one ffmpeg process (`-hwaccel auto`, `-stream_loop -1`) that writes
  NV12 frames to a pipe. A reader thread uploads the planes, and the GPU converts them
  to premultiplied RGBA.
- A video advances only while it's drawn. A paused layer stops reading, so ffmpeg
  blocks. In a measurement, that used 0.01 s of CPU in 3 seconds paused.
- A loop unused for 20 seconds is stopped.
- Offscreen renders wait for every frame (`BROMIGOS_WORLD_SYNC`).
- Alpha comes in three forms: `stacked` (colour over grey alpha, decoded in hardware),
  `native` (VP9 alpha, through libvpx) or `none`.

### Sound, the roll call and pausing

- **Sound.** A world's `[sounds] ambient` cues, such as Mire's frogs and crickets, play
  through `live/sound.py`. They play often while you work, a third as often when you're
  idle, and never when locked. Mute and `sounds.volume` apply.
  `[world] ambient_sounds = false` stops them.
- **Roll call.** At login, after the intercept, the world's lights wake one by one
  (`[rollcall]`; its `sound` key is reserved).
- **Pausing.** Worlds pause by the same rules as the den. A world catches up when it
  resumes. After an unlock, the keeper wakes over a few seconds as the lantern
  brightens.

### Craft overhead

Now and then one of a world's `[[actors.craft]]` crosses the sky (`kind = "flyby"` in
`live/actors.py`):

- **Distance.** Each pass picks a random distance. Nearer craft are bigger and faster,
  with less haze. A craft flies behind the layers in front of its `depth`.
- **Timing.** Passes come `every = [min, max]` seconds apart, at most `max` at once. Time
  to the next pass runs at `1 + gain × level` of its signal, so with the network signal,
  a busier network brings craft sooner.
- **No collisions.** A pass takes an altitude and path that never share a place and a
  moment with a craft already up. Otherwise it waits.
- **Bands.** `sky = [top, bottom]` keeps the whole craft inside a band. Tidewell uses it
  to keep craft above the trawlers' masts. Craft nearer than `near` can fly at
  `near_depth`, in front of a layer the far ones pass behind.
- **Looks.** Navigation lamps (`blink = "strobe"`, or a beacon's period), a moonlit rim
  on the top edges (`rim`), the night air's haze (`haze`) and exhaust `trails` that
  drift and fade. With `clouds`, the sky layer's lit clouds hide the craft and its lamps
  (`cloud_luma`). The moon's disc stays clear. Mirror water reflects craft like
  everything else behind the water.
- **Switches.** The `ships` animation switch turns craft off (`bromigos anim off ships`,
  or `space.traffic`), and so does reduced motion.
- **Cost.** About 0.2 ms of CPU a frame during a pass.
- **Test.** `bromigos-live world event flyby`, or `event flyby:<craft id>`.

### Cost

Measured with the real art at 2560×1440, rendering in real time at 30 fps on an RTX 5070
and a Ryzen 7 3700X:

| Scene | CPU, whole process | Notes |
|---|---|---|
| Mire | 8.8% of one core | Five agents, Hollis's loops, fireflies |
| Tidewell | 7.0% of one core | |
| The den | | 0.56 ms a frame |

A steady world frame takes about 1 ms of CPU, and 0.3–2 ms of GPU. Seamless loops are
decoded once and then played from the GPU. Each loop's ffmpeg process uses 4–6% of a
core for its first pass only. One-shot clips stream while they play. Nothing decodes
while paused.

### Try a world without switching themes

Offscreen, with `OFF_WORLD` set to a theme's folder:

```bash
OFF_WORLD=../themes/mire OFF_SCRIPT="0 w set cpu 0.95; 4 w event notify" \
  python3 tools/offscreen.py world out.mp4 20
```

On the desktop, with a world showing:

```bash
bromigos-live world state
bromigos-live world event critical
bromigos-live world set cpu 0.95
bromigos-live world clear
bromigos-live world rollcall
```

### Config

`[world]`: `enabled`, `dir`, `idle_after = 90` (seconds before the keeper and the
creatures doze), `ambient_sounds`.

### Mire

Mire is a night bayou.

| Thing | Shows | Signal |
|---|---|---|
| Sleeper heads, three in the foreground water | Your first three coding agents, oldest first | `agents` |
| Sleepers wading, moss-covered frames | Your other coding agents | `agents` |
| Hollis, the keeper | Your activity | `user` |
| His fishing line | Fills from the trade feed | fills |
| Herons | Notifications | `notify`, `critical` |
| Fireflies | This machine's network throughput | `net` |
| Mist, rain and thunder | CPU load | `cpu` |
| Two eyes, and a long shape | Trouble in the homelab | `health` |
| The mast's light | The homelab is all green | `lab_green` |
| The drone by the lantern | VECTOR's state | `vector` |
| Frogs on the pads and heads | Your activity | `user` |
| Crickets, as sound | Your activity | `user` |
| The moon and the light | The real moon, and dusk, night and dawn by the clock | clock |
| Stars | The time of night | clock |
| The crashed gunship, the wreckage, the boat | Nothing: they're the scene | none |

How each one behaves:

- **Sleeper heads.** When an agent starts, bubbles rise, a swell comes, the head breaks
  the surface and its eyes boot with a flicker. While the agent works, the eyes pulse
  slowly, spilling light on the water and the pads. When it needs you, the head rises a
  little, turns to you and its eyes double-flash amber, or red on an error. When it
  finishes, the head sinks, rings spread and the last bubbles rise.
- **Sleepers wading.** Further agents wade among the wrecks with their eye-lamps lit
  while working. When one needs you, it stops, turns to you and flashes amber. It settles
  into the water when finished, and sinks away when closed.
- **Hollis.** He fishes while you work, nods off in his rocking chair when you're idle,
  and slumps with the lantern dimmed when you lock the screen.
- **His fishing line.** It goes taut on each fill. A fish comes up for a win, a boot for
  a loss, and the line twitches for an opening.
- **Herons.** A heron rises off the shore for a notification. For a critical one, it
  flies at the screen, red-eyed.
- **Fireflies** (`live/fireflies.py`). Live particles drift on a slow, curling flow.
  Each blinks on its own rhythm, and near ones are reflected directly below. There are a
  handful when the network is quiet and hundreds during a big download, smoothed over 3
  seconds, plus a few more in deep night. They scatter when a Sleeper rises or sinks.
- **Mist, rain and thunder.** As CPU load climbs, the mist thickens, then drizzle
  starts, then a downpour hits the water. Lightning comes near 100%.
- **Two eyes, and a long shape.** At health 1, eyes appear by the shack's stilts. At
  health 2, a long shape appears too.
- **The drone by the lantern.** It hovers when VECTOR is idle, circles amber while he
  thinks, pulses while he speaks and faces you while he listens. It flickers red on an
  error, and is gone when he's off.
- **Frogs and crickets.** Frogs croak, with a puffed throat and a croak cue, and hop
  from pad to pad while you work. They're still when you're idle or locked. Crickets
  sing often while you work, less when you're idle and never when locked.
- **Stars.** Faint stars twinkle through gaps in the canopy and fade into the mist at
  the horizon. They're brightest in deep night and gone by day.

### Tidewell

Tidewell is the sea at night, seen from just under the surface. The waterline is a fifth
of the way down. Above it is a strip of sky, with Greywater Light small on its rock in
the upper right. The water below is the stage.

| Thing | Shows | Signal |
|---|---|---|
| The Choir, glowing swimmers | Your coding agents | `agents` |
| Maren, the keeper | Your activity | `user` |
| Greywater Light's beam | Homelab health, and the ingress rate | `health`, `ingress` |
| A storm | Something in the homelab is down | `storm` |
| Light shafts and caustics | The moon's or the day's light, moved by the swell | clock, `cpu` |
| Hulls at the surface | Network traffic in and out | `net_rx`, `net_tx` |
| Jellyfish blooms | Notifications | `notify`, `critical` |
| Silver fish in the moored trawler's net | Fills from the trade feed | fills |
| A school of fish, and seabirds | Your activity | `user` |
| The swell | CPU load | `cpu` |
| The tide | The moon, worked out locally | clock |
| The lamp-drone under the surface | VECTOR's state | `vector` |

How each one behaves:

- **The Choir.** Agents glide through the deep with a cyan glow. When one needs you, it
  rises, faces you and breaches with light and spray. When it finishes, it dives,
  leaving a trail.
- **Maren.** A tiny figure in the lamp room. She moves about while you work, sits by the
  glass when you're idle, and sleeps with the room dark when you lock the screen.
- **Greywater Light's beam.** It sweeps the surface strip. Its colour is the homelab's
  health: white, amber or red. Its turning speed is the ingress rate.
- **The storm.** Rain and lightning hit the surface strip when something in the homelab
  is down. The flashes flicker down the light shafts.
- **Hulls at the surface.** Trawlers come in from left to right with downloads, and
  haulers go out with uploads. You see them from below, with their running lights.
- **Jellyfish blooms.** They rise through the water for each notification, red for a
  critical one.
- **Silver fish.** Green flashes for a win, red for a loss, silver for an opening.
- **Fish and seabirds.** They school and wheel while you work, hold still when you're
  idle, and are gone when you lock the screen.

## The den plate and its variants

The fitted elements line up with only one family of images: the four den screens, the
floor pulses and the loops. So they switch on only for approved images:

- Every approved den image is composited onto the same **v1 plate**
  (`background.den_plate`), so all variants share its geometry.
- `[background.den_plates]` maps each approved image's **sha1** to a variant name: `den`,
  `empty`, `masked` or `v1`. `Background._load_under()` hashes the current wallpaper. A
  match turns on the fitted elements and the clean plate. Any other image is drawn as it
  is, with only the generic layers: rain, space, sweep and wipe. The log then says "not an
  approved den variant".
- The current choice is local state in `~/.local/state/bromigos/wallpaper/den.jpg`,
  switched by `bromigos wallpaper`. It's never a tracked file. The packaged den is the
  fallback.
- It's always the Wick's plate, so its sha1 matches. Under a colour theme,
  `scene.retint_plate()` recolours the fitted plate as it loads
  (`lib/bromigos_retint.py`). swaybg shows `wall.jpg`, the same recolour saved on disk.

### Adding a variant

1. Composite the new image onto the v1 plate, at the same size and position.
2. Render it offscreen, and check every fitted rectangle still sits on its screen.
3. Add its sha1 under `[background.den_plates]`.
4. If its mug should steam, add its name to `loops.steam`.

Never edit or re-save the wallpaper file to make something fit.

### Fitting coordinates

Everything fitted is in plate pixels: the `DEN` rectangles in `live/scene.py`, the
floor fit in `[floor]`, and `STEAM_BOX`, `HORIZON`, `FLOOR_X1` and `ROWS` in
`live/plate.py`. To find a rectangle, open the plate at 100% in an image viewer and read
its corners. Then render (`tools/offscreen.py bg out.png 2`) and look at the crop at
full size. The plate is 16:9, and other resolutions scale.

## Adding a new element

1. **Decide what it means.** Name the real reading or event it shows, or mark it as
   decoration and keep it calm. If it needs a reading the snapshot doesn't have, add it
   to `live/data.py` in the loop with the right rate, and read it with `d.get(key)`.
   Never poll in the frame.

   | Loop | Rate |
   |---|---|
   | `_local_loop` | 1 s |
   | `_slow_loop` | 5 s |
   | `_gpu_loop` | 1.5 s |
   | `_cluster_loop` | 25 s |

2. **Pick the route.** A self-contained effect over the whole background that needs only
   load, network and health can be a plugin shader layer (`layers/`), with no change
   here. Anything fitted to the den, using other data, or interacting with the existing
   layers belongs in the core: `scene.py` and `bg.frag`.
3. **Fit it.** For a den screen, add its rectangle to `DEN` in plate coordinates and
   pass it scaled with `self._px(DEN["name"])`. A sky element stays inside
   `u_space_rect` and multiplies by `sky`, so it draws on dark pixels only. Never cover
   the desk art.
4. **Pass the reading in.** Declare `uniform vec4 u_<name>;` in `bg.frag`, packing
   related values into one vec4. Set it in `Background.render()` with
   `f.f("u_<name>", ...)`. Write the drawing as a function, such as `vec3
   my_thing(vec2 px)`, and call it in `main()`. For a den screen, call it in `den()`
   with the `glass()` helper.
5. **Let the pause rules work.** The background drops to 0 fps when locked, under a
   fullscreen window or under a deck, so don't add timers of your own. Ease readings
   toward their target each frame, as `meter_v` does, so they don't jump once a second.
6. **Add a config key.** Add a switch, and any tuning, to `config.toml` in the right
   section, with a comment saying whether it's data or decoration. Read it with
   `cfg.get(...)` and a default, so an old config still works.
7. **Test it.** `tools/offscreen.py bg out.png 2 5` renders real frames headless. Check
   them at full size and at 1280×720. For a loop, check the seam. After
   `bromigos-live restart`, watch the frame cost in `bromigos-live status`.
8. **Document it.** Add a row to the table at the top and a section here, with the same
   fields. If it adds a key, update the comment block at the top of `config.toml` that
   lists what's data and what's decoration.

## Worked examples

### Change what an element shows: the left meter shows RAM

The left meter reads `cpu`. Memory is already in the snapshot as `mem`, a percentage
from `psutil.virtual_memory`, updated every second. In `Background.render()` in
`live/scene.py`, change one line:

```python
for i, k in enumerate(("cpu", "gpu")):          # before
for i, k in enumerate(("mem", "gpu")):          # after: left = RAM, right = GPU
```

Nothing else changes. The needle maps 0–100 to the scale and eases the same way. The
shader doesn't know what it shows.

Then update this file's Meters row and section to say the left meter shows memory in
use. Render the change (`tools/offscreen.py bg /tmp/m.png 3`), look at the meter, and run
`bromigos-live restart`.

VECTOR does this through his build loop, with the `update-visualization` skill. He calls
`build_begin`, renders before, makes the change, renders after, and calls `build_apply`
with a note such as "Updated: the den's left meter shows memory instead of CPU".

### Add a new element: a disk-activity lamp on the den

A small lamp that glows with disk writes. Disk throughput is already in the snapshot as
`disks`: each disk's read and write bytes per second, updated every second.

1. **Fit it.** Pick an unused lit spot on the desk art and add `"lamp": (x, y, w, h)` to
   `DEN`, in plate pixels.
2. **Pass the reading in,** in `Background.render()`:

   ```python
   w = sum(v["w"] for v in (d.get("disks") or {}).values())
   self.lamp_v += (min(math.log10(1 + w) / 8.0, 1.0) - self.lamp_v) * a   # eased; set to 0.0 in __init__
   f.f("u_lamp", *self._px(DEN["lamp"]))
   f.f("u_lamp_v", self.lamp_v)
   ```

3. **Draw it,** in `bg.frag`. Declare `uniform vec4 u_lamp; uniform float u_lamp_v;`,
   then add this to `den()`:

   ```glsl
   m = glass(px, u_lamp, uv, g);
   if (m > 0.0) c = mix(c, g + AMBER * u_lamp_v * exp(-dot(uv - 0.5, uv - 0.5) * 8.0), m);
   ```

4. **Config.** It follows `background.den`. Give it its own switch if it should turn off
   separately.
5. **Test and document.** Render it offscreen, check the frame cost, and add its row and
   section here.
