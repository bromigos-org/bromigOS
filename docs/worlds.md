# Worlds

A *world* is a theme whose wallpaper is a living scene. Everything that moves in it shows
something real: your AI coding agents at work, your network traffic, your notifications,
your homelab's health, and whether you're at the keyboard. The *live layer*, the program
that draws the animated background, draws it behind your windows.

bromigOS ships two worlds, Mire and Tidewell. The default theme, the Wick, has the den
instead: a painted radio room with live screens. This page says what each thing in them
shows, and describes the worlds planned next.

- To build a world, read [theming.md, "Make a world"](theming.md#make-a-world).
- Every element of the live layer, with its data and settings, is in
  [live/docs/ELEMENTS.md](../live/docs/ELEMENTS.md).
- For users, the manual's [Themes and worlds](../manual/src/themes-and-worlds.md) page.
- The [glossary](../manual/src/glossary.md) defines bromigOS's terms.

In the Bromigos stories, each world is the view from a *post*: one of the relay stations
on the worlds of the Drift. The post's *keeper* is in the scene. The stories themselves
are in the Bromigos world bible, `agents/LORE.md` in the platform repository. This page
is the product side. Which creature shows which reading is product design, not canon, so
it lives here and never in the world bible. If a keeper or post is renamed there, rename
it here too.

<!-- site:worlds-rules -->
## What every world does

- **Every moving thing shows real data.** If a source isn't available, what it drives
  isn't drawn. Nothing moves for decoration.
- **"Needs you" always looks the same.** Something turns to face you and signals: a
  machine turns and flashes its eyes, a leviathan breaches. Learn the gesture once and
  you can read it in every world.
- **The keeper mirrors you.** The keeper works while you work, dozes when you're idle and
  sleeps when the screen locks.
- **The ambient creatures follow you too.** They're busy while you work, settle when
  you're idle, and sleep or vanish when the screen locks.
- **The real clock drives day and night.** The moon shows its real phase.
- **VECTOR appears as something carrying his line.** VECTOR is the desktop's AI assistant.
  In the stories he never leaves his own post, so in each world he's a drone or a lamp,
  never VECTOR in person.
- **Login wakes the world.** At login, the world's lights come on one by one: the roll
  call.
- **The emblem keeps to its rules.** A world's version of the burn-in emblem carries a
  motto, never a callsign or a frequency ([theming.md](theming.md#the-emblem)).
- **Reduced motion is respected.** Under the `reduced` setting, a world keeps its look
  and its life at 0.4 of the pace, with no parallax, flicker, flashes or craft. Under
  `still`, it holds one picture and draws it again only when what it shows changes
  ([accessibility.md](accessibility.md)).

> **Planned.** These are designed but not built yet:
>
> - real weather from your location, as an opt-in;
> - a spoken roll call at login, where the post checks in and signs off with
>   **STILL LIT.**;
> - a lock screen and a screensaver of each world's own. Today every theme shares the
>   lock screen and the Drift screensaver, in its own colours.

<!-- site:worlds-sources -->
## Where the data comes from

| Source | What it is | Comes from |
|---|---|---|
| Agents | AI coding agents run by herdr: working, needs you, finished | herdr |
| Agents working | herdr's working agents, plus busy Claude Code sessions outside herdr | herdr, the process list |
| Network | Throughput, split into download and upload | this machine |
| Notifications | Desktop notifications, with critical ones flagged | this machine |
| CPU | This machine's load | this machine |
| Activity | Whether you're working, idle or locked | this machine |
| Lab health | Your homelab's services: up, degraded or down | `bromigos-homelab` |
| Local models | How hard your homelab's local models are working | `bromigos-homelab` |
| Fills | A personal plugin's fill events: a win, a loss or an opening | a personal plugin |
| Clock | Local time; the moon's phase is computed from it | this machine |

herdr is the terminal workspace manager for AI coding agents that bromigOS can install.
On a desktop without herdr, a homelab or the personal plugin, what those sources drive
simply isn't there, and the world is quieter. That's the first rule at work, not a
fallback to fake data.

<!-- site:world:mire -->
## Mire

![Mire: a stilt shack with a lantern-lit porch over black water, a sunken gunship
overgrown with moss, and fireflies under huge trees](images/world-mire.webp)

**Feel.** A bayou at night that swallowed a war. It's humid, slow and watchful, and kind to
whoever is on the porch.

**Look.** Black water, green mist, huge twisted trees hung with moss, lily pads and
firefly light. The palette sits close to the Wick's greens. The lantern on the shack is
the one warm light.

**Scene.** The stilt shack is the focus. Hollis sits in his rocking chair under the porch
lantern, with his boat tied below and the relay mast above. Across the water, a crashed
gunship from the Ledger Wars lies half-sunk, overgrown, its engine still glowing faintly.
Wreckage breaks the lily pads. Old war machines, the Sleepers, wade among the wrecks. The
designs are all original.

**Keeper.** Hollis Crane, fishing off the porch.

| What you see | What it shows |
|---|---|
| A half-sunk Sleeper's head, hand, shoulder and crown, in the foreground water | Your first four agents |
| Sleepers wading among the wrecks | Up to eight more agents |
| Hollis in his rocking chair | You: working, idle or locked |
| Rain, mist and lightning | Agents working, local models and the CPU |
| Fireflies | Network throughput |
| Craft crossing the sky now and then | Network traffic |
| Herons | Notifications |
| Frogs and crickets | Whether you're working |
| The light on the relay mast | Your homelab, all green |
| Two eyes, then a long shape by the stilts | Trouble in your homelab |
| A small drone by the porch lantern | VECTOR |
| Hollis's fishing line | A personal plugin's fills |

How they behave:

- **The Sleepers.** When an agent starts, bubbles rise and a piece of the Sleeper breaks
  the surface, its eyes flickering on. While the agent works, the eyes glow steadily and
  light the water. When it needs you, the piece rises a little, turns to you and its eyes
  flash amber, or red on an error. When it finishes, it sinks back and rings spread.
- **Hollis** works the line and rocks while you work. His hat tips down when you're idle,
  and he dozes in his chair when the screen locks.
- **The rain** is a drizzle while agents work, harder with more of them. It's heavier while
  your homelab's local models generate, and a downpour with thunder when the CPU runs high.
  It eases in over seconds and off over a minute, back to mist and fireflies. The
  fireflies go to ground in the rain.
- **The craft** are a Drift long-hauler, Pip Arro's Petrel on a parts run, and a Picket, a
  sentry drone still flying its patrol. One crosses behind the far trees every few
  minutes, sooner with more traffic. `bromigos anim off ships` turns them off.
- **A heron** lifts from the reeds for each notification. For a critical one, a heron
  flies straight at the glass.
- **The frogs** croak and hop between the pads while you work, and sit still when you're
  idle or locked. **The crickets** chirp often while you work, less when you're idle, and
  not at all when locked.
- **The thing in the water** shows as two eyes by the stilts when your homelab is
  degraded, and a long shape too when something is down. It's never shown whole.
- **The drone** turns to you when VECTOR speaks.
- **The fishing line** goes taut on a fill. Hollis lands a fish for a win, and a boot comes
  up for a loss.

> **Planned for Mire.** The lock screen: moss grows over the emblem while the lantern
> stays lit. More sounds: water lapping the stilts, the rocking chair's creak, Hollis's
> radio, a Sleeper's servos waking.

<!-- site:world:tidewell -->
## Tidewell

![Tidewell: a lighthouse on a rock above a night sea, trawlers at the surface, and
glowing creatures, fish and jellyfish below the waterline](images/world-tidewell.webp)

**Feel.** An ocean world at the edge of a storm: vast, cold and full of song.

**Look.** Slate water and sky, rust-red hulls, and the cyan of the Choir's light under the
swell. The lighthouse beam is the brightest thing in the scene.

**Scene.** Mostly underwater. The waterline sits high, about a fifth of the way down. Above
it is a strip of night sky and sea, with Greywater Light small in the corner on its rock,
the Sliver. Below is the sea itself: kelp on rock shelves, clouds of small glowing fish
(lampfry), jellyfish rising through the moonlight, and the dark deep where the Choir
glide.

**Keeper.** Maren Holt, in the lamp room, logging the Choir's songs.

| What you see | What it shows |
|---|---|
| The Choir, great glowing leviathans | Your agents, one each |
| Maren in the lamp room | You: working, idle or locked |
| Trawlers at the surface | Network traffic: downloads come in, uploads head out |
| Craft crossing the sky now and then | Network traffic |
| The swell, and the light patterns under it | The CPU |
| Greywater Light's beam | Your homelab's health and its traffic |
| The linebloom, a glowing reef down the rock | Your homelab's health |
| A storm with lightning | Something in your homelab is down |
| Jellyfish blooms | Notifications |
| Lampfry and seabirds | Whether you're working |
| Resident jellyfish | Nothing: they're the water's own life |
| A lamp-drone circling the gallery rail | VECTOR |
| Veilwings and burrs | A personal plugin's fills |

How they behave:

- **The Choir** glide through the open water with a cyan glow while their agents work.
  Some swim far off, behind the kelp. When an agent needs you, its leviathan rises and
  breaches with light and spray, then waits glowing under the surface and breaches again
  now and then. When an agent finishes, it dives, leaving a glowing trail.
- **Maren** writes at her desk while you work, sits back when you're idle, and sleeps on
  the logbook when the screen locks.
- **The trawlers** coming in are downloads, and those heading out are uploads.
- **The craft** are rig-hoppers with a container slung under them, a trawler's
  fish-spotter, Pip Arro's Petrel and a Drift long-hauler far up. They fly above the
  trawlers' masts. `bromigos anim off ships` turns them off.
- **The beam's colour** shows your homelab's health. It turns faster with more incoming
  requests. With no homelab data, the lamp is dark.
- **The linebloom** breathes calmly in its own colours, violet, pink, orange, gold and
  cyan, while every node and service is up. It turns amber on a warning, and pulses slowly
  red on an alert.
- **A jellyfish bloom** rises through the water for each notification. It's red when the
  notification is critical.
- **The lampfry** drift in slow clouds under the moonlight while you work. They're dim and
  nearly still when you're idle, and gone when locked. **The seabirds** wheel round the
  light while you work, settle on the islet when you're idle, and are gone when locked.
- **The fills:** a pair of green veilwings sweeps in low for a win, and one smaller, paler
  veilwing for an opening. Two burrs with coal-red lights rise out of the deep for a
  loss.
- **The tide** follows the real moon.

> **Planned for Tidewell.** Rain and fog from the real weather. A screensaver that dives
> slowly into the deep among the Choir. The lock screen: the beam turning over the emblem.
> Sounds: waves, a buoy bell, a foghorn, and a song phrase for each agent, so you can tell
> which one is calling.

<!-- site:world:wick -->
## The Wick's den

The den is the default theme's live background. It isn't a world in the format sense:
the live layer draws it directly, with no `world.toml`. Its main elements:

| What you see | What it shows |
|---|---|
| The oscilloscope by the desk | Network throughput over the last 48 seconds |
| The big monitor's relay map | Your homelab's nodes and links |
| The two meters on the desk | CPU and GPU load |
| The rain of glyphs | CPU load |
| Bursts in the rain | Notifications and homelab alerts |
| Pulses on the floor grid | Download (toward you) and upload (away) |
| Ships and debris outside | Network traffic |
| The relay station's beam | Your homelab, all green |
| An amber or red tint | Running hot, or something down |
| A sweep across the screen | This machine's parts, with live readings |

The full list, with each element's data, code and settings, is in
[live/docs/ELEMENTS.md](../live/docs/ELEMENTS.md).

The den doesn't show your agents. The Swarm deck (**Super+Shift+S**) does, as starships.

> **Planned for the den.** Agents as craft in the den, with the same "needs you" gesture
> as the worlds.

## Planned worlds

> **Planned.** None of these worlds is built. Rime, Sunder, Cinder, Lowtown, Highwind and
> Deepvein ship today as colour themes, with the den behind them. Cradle has no theme yet.
> The order of work is Rime and Sunder first, then Cinder, Lowtown, Highwind, Deepvein and
> Cradle.

Each design below follows the same data mapping, so you can compare them.

<!-- site:world:rime -->
### Rime

An ice moon that kept talking for ten years with nobody answering: lonely, stubborn and
bright. Blue-white ice, black sky, aurora green, and the sodium-orange floodlights of the
ice-crawlers.

**Scene.** From inside Station Nine, a half-buried relay hut, through a frosted window onto
the glacier. A long-range dish turns on the roof. Distant outposts sit on the horizon.

**Keeper.** Juno Varga at the hut's radio. She turns the dish and talks into the mike while
you work, wraps her hands round a mug when you're idle, and sleeps in the bunk under a pile
of coats when the screen locks.

- **Agents:** ice-crawlers, tracked and floodlit. They sweep their lights as they crawl.
  One that needs you turns toward the hut and fires a flare. A finished one parks and its
  lights go out.
- **Network:** the aurora, brighter and faster with traffic.
- **Notifications:** a signal fire at a distant outpost.
- **CPU:** a blizzard, from still air to whiteout.
- **Lab health:** a Frostback's shadow under the ice. At its worst, the ice cracks.
- **Fills:** a drill rig strikes ore for a win, or a dry hole for a loss.
- **VECTOR:** a heated drone that taps at the window when he speaks.
- **Activity:** ice-foxes play in the lee while you work, and curl up when you're idle.
- **Sound:** wind, the dish motor, the radio's hiss, crawler tracks grinding, ice
  settling.
- **Lock screen:** frost creeps over the screen and the emblem, and thaws on unlock.

<!-- site:world:sunder -->
### Sunder

A salvage desert of wrecks and clans: hot, bright and resourceful. Ochre dunes, the hulls
of fallen dreadnoughts, a white sun and a small red one, and patched sailcloth.

**Scene.** From the Spine, the relay welded to a fallen cruiser's spine, looking over the
dunes toward other wrecks. Salvage cranes stand on the nearest hulls.

**Keeper.** Tamsin Rook, working on the relay with a toolbag. She works while you work,
sits on the spine with her legs dangling when you're idle, and sleeps under a tarp when
the screen locks.

- **Agents:** sand-skiffs sailing the dunes. One that needs you turns toward the Spine and
  flashes its sail. A finished one furls its sail and beaches.
- **Network:** night caravans of armoured cargo-beasts, longer with more traffic.
- **Notifications:** a heliograph flash from another wreck.
- **CPU:** a sandstorm, from clear air to a full storm.
- **Lab health:** the sky, from clear to hazy orange to a red storm-wall.
- **Fills:** a salvage crane lifts a hull plate cleanly for a win, or drops it for a loss.
- **VECTOR:** a scout drone with a wind-vane, hovering off the spine.
- **Activity:** scrap lizards sun on the plating while you work, and hide when you're
  idle.
- **Clock:** the twin suns follow the real time.
- **Sound:** wind over sand, sailcloth snapping, metal ticking as it heats and cools,
  crane cable creaking.
- **Lock screen:** sand drifts over the emblem.

<!-- site:world:cinder -->
### Cinder

Foundries that never stopped: heat, noise and sparks, with something patient underneath.
Black iron, molten orange, an orange sky and steam.

**Scene.** From the cab of a dead forge crane, looking down over the foundry halls,
gantries and lava rivers, with the volcano behind.

**Keeper.** Brask, at a workbench in the crane cab. He works on a housing while you work,
leans back when you're idle, and sleeps with his boots on the bench when the screen locks.

- **Agents:** forge-golems, half-built, walking the gantries. One that needs you turns
  toward the cab and raises a glowing arm. A finished one steps into a cooling bath in a
  cloud of steam.
- **Network:** molten crucibles pouring, more often with more traffic.
- **Notifications:** an ember burst.
- **CPU:** the furnace glow, from a low glow to a shower of sparks.
- **Lab health:** the volcano smokes when something is degraded, and erupts when it's
  down.
- **Fills:** an ingot is stamped clean for a win, or scrapped for a loss.
- **Activity:** cinder-crows wheel over the stacks while you work, and roost when you're
  idle.
- **Sound:** furnace roar, hammers, the cooling bath's hiss, chain and cable, crows.
- **Lock screen:** the emblem is cast in molten metal and cools. The flame cools to true
  black, as the emblem's rules require.

<!-- site:world:lowtown -->
### Lowtown

A rain city at night: neon, jazz and bounty boards. Stylish, lonely and awake. Wet
streets, neon in pinks, blues and greens, elevated rails and fogged glass.

**Scene.** From inside the Low Note, a basement jazz bar, looking up through a
rain-streaked window at the street. The bar's neon sign is in frame. Its second O is a
green ring around a black glass flame.

**Keeper.** Della Ash at the piano. She plays while you work, sits with a glass when you're
idle, and closes the lid and rests her head on it when the screen locks.

- **Agents:** hover-cabs weaving between towers. One that needs you pulls up at the window
  with its hazards blinking. A finished one lands and goes dark.
- **Network:** elevated trains, more and longer with more traffic.
- **Notifications:** a billboard flips.
- **CPU:** street traffic, from sparse to gridlock.
- **Lab health:** the city's power flickers when degraded. A district blacks out when
  something is down.
- **Fills:** a ticker crawling round a tower, each fill in green or red.
- **VECTOR:** a holographic figure on the bar sign that flickers to life when he speaks.
- **Activity:** crowds while you work, thinning when you're idle. A stray cat sleeps on
  the sign.
- **Sound:** rain, piano, a bar's murmur, trains overhead, wet tyres.
- **Lock screen:** rain runs down the window over the neon emblem.

<!-- site:world:highwind -->
### Highwind

A cloud city in a gas giant's storm bands: airy, vast and gentle. Banded cloud in ambers
and creams, airship envelopes, and the dark bulk of the station's rings above.

**Scene.** From the kite-mast gondola trailing below the station, looking across the cloud
bands. The kite's canvas, with the flame painted on it, flies overhead.

**Keeper.** Pip Arro in the gondola, checking cargo manifests and the cable. Pip works
while you work, hangs a leg over the side when you're idle, and sleeps in a hammock when
the screen locks.

- **Agents:** airships crossing the bands. One that needs you circles the gondola,
  flashing its signal lamp. A finished one moors at the station.
- **Network:** sky-whales, more of them with more traffic.
- **Notifications:** lightning in the clouds.
- **CPU:** wind and cloud bands, from still to racing.
- **Lab health:** a storm-eye forms and darkens as things get worse.
- **Fills:** cargo nets of glowing gas canisters, hauled up for a win or cut loose for a
  loss.
- **VECTOR:** a lantern weather-balloon bobbing by the gondola.
- **Activity:** kite-birds ride the updrafts while you work, and perch on the cable when
  you're idle.
- **Sound:** wind, cable hum, distant airship engines, the sky-whales' low calls.
- **Lock screen:** the clouds part to show the emblem.

<!-- site:world:deepvein -->
### Deepvein

Caverns miles down that sing: dark, glittering and close. Black rock, crystals in cold
blues and violets, warm headlamp light, and the soft glow of crab shells.

**Scene.** The resonance chamber, with the relay among the crystals. The lift head is at
the edge of the frame, with the flame carved into the stone.

**Keeper.** Ora Slate at her instruments among the crystals. She works while you work,
sits listening to the crystals when you're idle, and sleeps on a cot by the lift when the
screen locks.

- **Agents:** miners' headlamps moving through the tunnels. One that needs you swings its
  lamp toward you. A finished miner rides the lift up.
- **Network:** crystals lighting in sequence, faster with more traffic.
- **Notifications:** a chime, and a crystal flaring.
- **CPU:** from a slow drip to falling dust.
- **Lab health:** dust and loose stone when degraded, a tunnel caving in when something is
  down.
- **Fills:** an ore vein glints for a win, or shows a dull seam for a loss.
- **VECTOR:** a glowing probe drifting among the crystals.
- **Activity:** cave crabs crawl the walls while you work, and keep still when you're
  idle.
- **Sound:** the crystals' resonance, dripping water, the lift's chain, distant picks, the
  click of crab legs.
- **Lock screen:** the emblem grows in crystal.

### Cradle

Earth, now: a suburban garage at night, a kid with old radio gear, listening to the bands
everyone else filters out. Real and small, with only the signal strange. A bare bulb,
pegboard, a workbench of second-hand radio gear, a CRT TV and a porch light outside. The
ring and flame are drawn on the radio's case in green marker.

**Scene.** The garage from the workbench, with the door half up onto the driveway, the
street and a streetlight beyond.

**Keeper.** The kid at the ham radio with headphones on, never named. The kid tunes and
scribbles while you work, leans back when you're idle, and falls asleep on the bench when
the screen locks.

- **Agents:** cars passing on the street. One that needs you pulls into the driveway with
  its headlights on the garage door. A finished one parks and its lights go out.
- **Network:** traffic as signal on the radio's waterfall display.
- **Notifications:** the wall phone rings.
- **CPU:** the VCR clock and the TV's static, from steady to heavy.
- **Lab health:** the streetlight, steady, then flickering, then out.
- **Fills:** a pager on the bench buzzes with each fill.
- **VECTOR:** a voice on the CB radio, which crackles when he speaks.
- **Activity:** a cat watches from the window and moths circle the porch light while you
  work. Both settle when you're idle.
- **Sound:** radio hiss and squelch, the TV, the fridge's hum, crickets outside, the
  phone's bell.
- **Lock screen:** the TV switches off to a dot, and the emblem shows in its afterglow.

In the stories, Earth can receive but never be heard. So nothing in this scene shows the
kid's answers being heard. At login the kid hears the roll call and answers it, and no
reply comes.
