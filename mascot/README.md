# STATIC's art (`bromigos-mascot-art`)

This folder holds the painted art of STATIC, the Bromigos mascot, that bromigOS ships. It
has two parts:

- **The guide's host** (`static/`): short loops that host Den TV's channel guide.
- **Den TV's bumps** (`bumps/static/`): short clips that play between shows and on a channel
  change, mostly late at night.

A third part isn't in the package: **the station's crew** (`crew/`), five cut-outs that the
Lab board's page shows on its station ([docs/board.md](../docs/board.md)).

It's art only. The code that shows it is in `lib/bromigos_static_art.py` (the guide) and
`lib/bromigos_bumps.py` with `live/live/tvbumps.py` (the bumps). Without this package, the
guide draws STATIC's code-drawn placeholder, and the den plays no bumps.

STATIC is signal first and a body second. He rides many machines, called **shells**, and
each shell has its own job. The art casts them by what's happening. NOIR, a host in a hover
pod, hosts. RIG's LINEMAN fixes things. RECON's OWL keeps watch. (In the Bromigos stories,
they crew a small ship between the relay posts.)

## The guide's host

`static/manifest.json` names one loop per state of the guide's Tonight card, at two
heights (168 and 336 pixels). Each loop is about four seconds of animated WebP: a
two-second stretch of a bump's clip, played forward then back so it loops without a jump.

| Name | When the guide shows it | The shell |
|---|---|---|
| `host` | What's coming up next | NOIR hosting the late-night broadcast |
| `snow` | The channels are being read | STATIC's signal racing into NOIR's console |
| `antenna` | There are no channels yet | OWL searching the dark for a signal |
| `asleep` | The live layer isn't running | NOIR powered down for the night |
| `whack` | Something can't be read | LINEMAN fixing a junction box |

Each name has `"min": 96`. Below 96 pixels, such as a terminal's half-blocks, the
placeholder draws instead. Each name's `about` is its hover hint.

## The bumps

`bumps/static/bumps.json` lists the bumps. Each one is a silent H.264 clip at 1248x720 and
32 frames a second, with no sound of its own. The den draws a bump's caption in the theme's
colours. No clip has text painted in.
[live/README.md, "Bumps"](../live/README.md#bumps) explains when they play and how to make
your own pack.

| Bump | Roles | Caption | What happens |
|---|---|---|---|
| `still-lit` | open, between | STILL LIT | OWL keeps watch on a cliff at night. It's the night block's ident. |
| `right-back` | between | BACK IN A MOMENT | LINEMAN hangs from a cable, fixing a junction box in a shower of sparks. |
| `cable-run` | tune, between | | LINEMAN rides a power cable down a ship's corridor. |
| `late-night` | between | STAY TUNED | NOIR hosts the late-night broadcast from his pod. |
| `signal-in` | tune, between | | STATIC's signal races down a cable into NOIR's console. |
| `takeover` | between | | A dormant repair robot wakes up as LINEMAN. |
| `crew` | between | | The crew on the ship: OWL at the viewport, LINEMAN at a junction box, NOIR on the bridge. |
| `sign-off` | close | SIGNING OFF | NOIR powers down for the night. It's the night block's sign-off. |

## The station's crew

`crew/` holds five cut-outs: one figure each, on a clear background, 300 pixels high.
The Lab board's station (Lamplight) stands them where a real event needs them. The
board's build copies them into its page (`board/web/scripts/art.mjs`), so they ship in
`bromigos-board-web`, not in this package.

| File | The shell | Where the station shows it |
|---|---|---|
| `owl.webp` | OWL on comms duty, listening | On the mast, while all is well |
| `owl-scan.webp` | OWL crouched, looking down | On the mast, while something needs you |
| `lineman.webp` | LINEMAN in his harness, welding | At the machine that needs you |
| `lineman-stand.webp` | LINEMAN kneeling at an open panel | In quarters, off duty |
| `noir.webp` | NOIR in his pod, seen from behind | In quarters, and in the booth when a show is on |

Each was painted from its shell's locked board with Qwen-Image-Edit-2511, cut out with
Lucida (MIT) and resized. `provenance.jsonl` has three lines for each, under its
`crew/<name>.webp`: the painting, the cut-out and the resize. SPARK, HERMIT and EXO have
no cut-out here, because their boards aren't locked: the station names them in words.

## How it was made

Everything here was made on the lab's own GPU, with no cloud service and no credits. Every
model is under Apache-2.0 or MIT.

1. **Panels.** The scene boards were painted with Qwen-Image-Edit-2511, with STATIC's
   approved concepts as identity references. BLACKFLAME locked them on 2026-10-31. For the
   two transformations, the same editor made a second frame from a panel: the robot
   dormant (for `takeover`) and powered down (for `sign-off`).
2. **Clips.** Wan 2.2 I2V-A14B animated each panel at 832x480 and 16 frames a second. The
   transformations use its first-and-last-frame mode, between a panel and its edit.
3. **Upscale.** SeedVR2 7B upscaled each clip to 1248x720, and RIFE 4.9 doubled its frames
   to 32 a second.
4. **Cut.** `tools/cut.py` (ffmpeg) fades each clip in and out and holds its last frame
   briefly. It joins the crew's three shots with a quarter-second of green interference.
   `tools/host_art.py` cuts the guide's loops.

`provenance.jsonl` has one line for each panel edit, clip and upscale: the model, its
licence, the seed, the prompt and the time it took.
