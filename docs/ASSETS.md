# Assets: what may ship

This is the checklist for every asset bromigOS ships or shows: art, icons, fonts, sounds,
voices, 3D models and the images in these docs. Nothing ships until it has a row here with
a clear answer.

The code is licensed `MIT OR Apache-2.0`. The Bromigos brand assets are all rights
reserved. The table gives each asset's answer in a few words. [How each was
made](#how-each-was-made) has the detail, and [Provenance](#provenance) has the terms of
the models used.

## The checklist

| Asset | Source | Ships? | Notes |
|---|---|---|---|
| Den TV controller (`live/live/tvosc.lua`) and MEDIA rotary dial | Drawn and written for bromigOS | yes | `MIT OR Apache-2.0`; no vendored mpv scripts or art |
| STATIC's placeholder: the code-drawn rig and terminal pixel head (`lib/bromigos_static.py`, `lib/bromigos_static_term.py`) | Drawn in code for bromigOS, from lab concept sheets | yes, until his rendered art ships | No generated pixels. The concepts were Qwen-Image 2.1 (non-commercial); [see the notes](#static-the-mascot) |
| STATIC's rendered art (an art folder with `manifest.json`) | To come: modelled and rendered in Blender | not yet | Needs its own row and provenance before it ships |
| Dictation panel and `dictation.webp` | Drawn for bromigOS; nested render with synthetic speech | yes | No desktop capture, audio, private text or external art |
| Code: the core, widgets, live layer, VECTOR, scripts | Written for bromigOS, first on the operator's desktop | yes | `MIT OR Apache-2.0` |
| Lab console test snapshot (`homelab/tests/snapshots/lab-tui.svg`) | Textual render with recorded fake readings | yes | No real desktop or lab data |
| Lab job cancellation (`lab-job-cancel.webp`) | Offscreen Textual render of the fake job fixture | yes | Drawn from our code; made-up job, no desktop capture |
| Bromigos palette, emblem ("the burn-in") and lore | Bromigos original | yes, as brand assets | Licensed apart from the code |
| Bromigos logos, favicons, lockups and house palette (`brand/`) | Traced from the canon `bromigos-logo.png` | yes, as brand assets | Source only, not packaged. No likeness |
| The canonical burn-in (`theme/emblem/identity.json`, `flame.svg`) | Bromigos original | yes, as a brand asset | In `bromigos-core`. Every emblem kit is drawn from it |
| Geist and Geist Mono fonts | Vercel, SIL OFL | yes | Keep the licence file |
| Icons and cursor | Generated or recoloured from Breeze Dark (LGPL) | **yes** (operator, 2026-10-08) | Keep Breeze's attribution where derived |
| The bar's battery and power-profile icons (`theme/icons/{bat,power}*.svg`) | Drawn for bromigOS | yes | Recoloured per theme |
| The bar's idle and Settings icons (`theme/icons/{eye,cup,gear}*.svg`) | Drawn in code by `theme/tools/build-icons.py` | yes | Recoloured per theme |
| The bar's Bluetooth icons: the rune, the battery cells and the kinds of device (`theme/icons/{bt,btcell}*.svg`) | Drawn in code by `theme/tools/build-icons.py` | yes | Recoloured per theme |
| The Bluetooth panel's device holograms (`desktop/lib/bromigos_driftglass.py`) | Drawn in code, at run time | yes | Wireframes in the theme's colours; no image files |
| The app launcher's icons (`theme/app-icons/`) | Drawn in code by `theme/tools/build-app-icons.py` | yes | Brand style, no generated art |
| The GPU device table (`core/crates/bromigos-core/data/gpu-ids.tsv`) | Read from NVIDIA's and Mesa's lists by `tools/hw/gpu-tables.py` | yes | Facts only, none of their text |
| Den wallpaper with the chair empty, and its lock twin | Generated with nolgia, 2026-10-04 | **yes** (operator, 2026-10-08) | On bromigos.org |
| Den wallpaper, masked | Made from the likeness art, burn-in over the face | **yes** (operator, 2026-10-08) | The keeper's face is always under the burn-in |
| Den wallpaper with the operator's likeness | Personal | **no** | The bare face never ships or goes on the site |
| Mire and Tidewell placeholder art and sounds | Drawn and synthesised by code | yes | Replaced as the real art lands |
| Mire art: comp, plates and layers | Generated with nolgia | **yes** (operator, 2026-10-08) | On bromigos.org |
| Mire actors | Generated with nolgia, cut out locally | **yes** (operator, 2026-10-08) | No likeness of a real person |
| Mire loops and clips | Generated with nolgia, looped locally. The Sleeper's clips upscaled with SeedVR2 7B on the lab | **yes** (operator, 2026-10-08) | On bromigos.org |
| Tidewell art: comp, plates and layers | Generated with nolgia | **yes** (operator, 2026-10-08) | On bromigos.org |
| Tidewell actors and loops | Generated with nolgia, matted locally | **yes** (operator, 2026-10-08) | The Choir is an original creature |
| Craft overhead in Mire and Tidewell | Generated with nolgia, cut locally | **yes** (operator, 2026-10-08) | Original designs |
| 3D holograms: the workstation, the Wick and the rack | nolgia concepts, image-to-3D | **yes** (operator, 2026-10-08) | On bromigos.org, without live readings |
| 3D holograms made on the homelab: the worlds' posts, creatures and craft | Open models on the homelab, no credits | **yes** (operator, 2026-10-08) | Research and community licences. See [the notes](#3d-holograms) |
| 3D burn-in emblem | Extruded from the Wick's emblem | yes, as a brand asset | In `bromigos-vector` |
| The Drift map's lore catalogue (`live/lore/catalog.json`) | bromigos.org's public lore export, copied by `tools/lore/sync-catalog.py` | yes, as a brand asset | In `bromigos-live`. A user's `[driftmap] catalog` replaces it |
| Swarm starship model | Procedural, original design | yes | |
| VECTOR's avatar, the relay-light construct | Drawn in code | yes | Part of the code |
| Sound cues | nolgia sound effects (ElevenLabs) | **yes** (operator, 2026-10-08) | On bromigos.org |
| VECTOR's designed caretaker voices | Designed from text with Qwen3-TTS VoiceDesign | likely yes | Confirm the model card adds no terms on output |
| The voice guide's clips (`lib/guide/clips/`) | Spoken by Qwen3-TTS Base from the designed voice `vector-ref-A`, with VECTOR's shimmer | as the designed voices | Made by `tools/voice/make-clips.py`; no personal cast |
| The operator's personal voice cast | Designed in Fish Audio | **no** | A personal setting, for another product |
| Revolver Lynx voice | A copy of a Fish library voice | **no** | A third-party upload |
| Any cloned voice of a real person or character | | **never** | |
| Kokoro, Qwen3-TTS, Whisper and Qwen3 embedding models | Apache-2.0 or MIT | yes, downloaded at install | Never vendor the weights |
| VECTOR's skills (`skills/*.md` in the vector repository) | Written for the desktop | yes, the generic ones | Anything naming a person's hosts stays in their dotfiles |
| Peripheral modules (`peripherals/`) | Written for the operator's desktop, generalised | yes, as code | Dependencies aren't vendored. No keymap file ships |
| The README's header emblem (`themes/wick/emblem/emblem-512.png`) | The Wick's emblem kit | yes, as a brand asset | Shown at the top of the README |
| README pictures from the render set (eleven files and an animated loop) | Offscreen renders by `tools/screenshots/render.py`, with demo readings | yes | No faces, no real hostnames. [List](#docs-and-readme-images) |
| Manual pictures (`manual/src/images/`) | Offscreen renders and bromigos.org stills, with demo readings | yes | bromigOS only, no likeness, no lab hosts. [List](#manual-pictures) |
| The built manual's page furniture (`bromigos-manual`, and the published manual) | mdBook's theme: Open Sans (Apache-2.0), Source Code Pro (OFL 1.1), Font Awesome Free icons (CC BY 4.0), highlight.js (BSD-3-Clause), clipboard.js, elasticlunr and mark.js (MIT), mdBook's own scripts and styles (MPL-2.0) | yes | Built by mdBook. The fonts' licence files ship beside them |
| bromigOS repository mirrorlist | bromigOS source, with a public package URL | yes | Text only |
| mehshell theme colour files and test fixtures | Generated from bromigOS theme colours by `lib/bromigos_prompt.py` | yes | Text only; no personal data |
| Docs images from bromigos.org (six files) | The site's published stills | yes | Offscreen renders with demo data. [List](#docs-and-readme-images) |
| Docs images rendered offscreen (twelve files) | bromigOS's own test tools | yes | No faces, no real hostnames. [List](#docs-and-readme-images) |

## How each was made

### The den wallpaper

- **Chair empty, and the lock twin**
  (`desktop/wallpaper/bromigos-{den,lock}-empty-2560x1440.jpg`). Generated with nolgia on
  2026-10-04 using gpt-image-2.5-flare. The den was made from text, then a masked edit
  took the figure out.
- **Masked.** Made from the likeness art with the burn-in over the face, using
  gpt-image-2.5-flare.
- **With the operator's likeness.** Personal and out of canon. It never ships.

### Mire

- **Comp, plates and layers** (`themes/mire/backgrounds/`). Made with gpt-image-2.5-flare
  through nolgia. Comp v3 used the den wallpaper as a style reference. Masked edits v4 to
  v6 added the sunk gunship and wreckage, the stars, the half-submerged Sleeper pieces and
  the frogs, and made the porch without Hollis. The layers were split locally with Depth
  Anything V2, SAM and LaMa. The painted fireflies and agent pieces were removed. The
  recipes are in `themes/mire/art.toml`.
- **Actors** (`themes/mire/live/actors/`). Hollis three times, the heron twice, three
  frogs, two Sleepers, and the four Sleeper pieces with their light masks. Made with
  gpt-image-2.5-flare, except the wading Sleeper, made with seedream-4.5. Cut out locally
  with BiRefNet. The pieces were cut from the comp with SAM.
- **Loops and clips** (`themes/mire/live/loops/`, `live/clips/`). The living backdrop,
  Hollis working, his head and hand idling, turning, and the Sleepers rising and
  submerging. The backdrop was made with minimax-h3 at 2K from the clean plate. The rest
  used seedance-1-5-pro with the start and end frames pinned. They were looped, masked and
  cut locally.
- **The Sleeper's clips, sharpened** (`sleeper-{head,hand}-{idle,turn}.mp4` in `loops/`,
  `sleeper-{head,hand}-{rise,submerge}.mp4` in `clips/`). On 2026-10-09 all eight were
  upscaled with SeedVR2 7B on the lab, with no credits. The hand was upscaled 2×, from
  640×360 to 1280×720. The head was upscaled 1.5×, from 960×540 to 1440×810. That is more
  than the 1.34× it is drawn at on a 3440-wide screen. Each clip ran as two overlapping
  segments, to stay inside the lab's limit for a clip job, and the segments were joined
  with a crossfade.
  The detail SeedVR2 added was then steadied where the scene holds still, and each frame
  keeps the original's colour and brightness. The rise clip's first and last frames take
  the detail of the frames they meet. The clips are H.264 at 24 fps as before, converted
  with the BT.709 matrix that the live layer uses for clips taller than 576 lines. Their
  masks are unchanged.

### Tidewell

- **Comp, plates and layers** (`themes/tidewell/backgrounds/`). Made with
  gpt-image-2.5-flare through nolgia. Comp v3 used the den wallpaper as a style reference.
  One masked edit removed the trawler and jellyfish. Another, on the layers' composite,
  painted out the silver fish, and `theme/tools/plate-patch.py` wrote it back. The layers
  were split locally with Depth Anything V2, SAM and LaMa. The recipes are in
  `themes/tidewell/art.toml`.
- **Actors and loops** (`themes/tidewell/live/`). Maren twice, the Choir leviathan, the
  jellyfish, and the trawler's hull and net. A masked edit took the net off the hull, and
  the net was cut from the first trawler and mirrored. The loops are the Choir, jellyfish,
  lampfry, veilwing, burr and linebloom. Stills were made with gpt-image-2.5-flare on
  black. Loops were made with seedance-1-5-pro and seedance-2.5, with the start and end
  frames pinned. They were looped, cropped and matted locally with
  `theme/tools/glow-loop.py`. The Choir isn't modelled on any film's creature.

### Craft overhead

The craft in `themes/{mire,tidewell}/live/actors/craft-*.webp`: the Drift long-hauler, Pip
Arro's Petrel and the Picket, plus the rig-hopper and the fish-spotter. They were made
with gpt-image-2.5-flare as two sheets on grey, with each world's painting as a style
reference. Backgrounds were removed with remove-background. Then they were cut, re-matted
and sized locally with `theme/tools/craft-sprites.py`. They're original designs, not
modelled on any film's or game's craft.

### Placeholders

The Mire and Tidewell placeholder art and sounds (`themes/{mire,tidewell}/backgrounds`,
`live/actors`, `live/sounds`) are drawn and synthesised by
`theme/tools/placeholder-worlds.py`. The real art replaces them as it lands, and that art
needs its own row.

### 3D holograms

- **The workstation and the Wick** are in the vector repository's `assets/holo/`, in
  `bromigos-vector`. **The rack** is in `homelab/holo/`, in `bromigos-homelab`, with its
  subtitle made generic and no lab name. Each started as a gpt-image-2.5-flare concept
  through nolgia, became 3D with hunyuan3d-v3 through fal, and was decimated and baked
  locally with VECTOR's `tools/holo/`. They're on bromigos.org without their live-reading
  bindings. A personal plugin's own model stays in that user's dotfiles.
- **Made on the homelab** on 2026-10-08, with no credits. These are the worlds' posts and
  creatures in `themes/*/holo/`: the stilt shack and a Sleeper, Greywater Light and the
  Choir, Station Nine, the Spine, the crane cab, the Low Note, the Petrel and the resonance
  chamber. The shared ones in `theme/holo/` are the long-hauler and an unlisted relay.
  - Concepts came from Qwen-Image-2.1. The creatures and craft used the worlds' own art
    as a reference image.
  - BiRefNet cut them out, and Hunyuan3D 2.1 made the shapes.
  - The masters were decimated and baked locally with VECTOR's `tools/holo/`.
  - Each collection's `generations.jsonl` records every job's prompt, seed and licence.
  - The operator decided on 2026-10-08 to publish them under the site's terms.
    Qwen-Image-2.1 is under the Qwen Research License, for research or evaluation only.
    Hunyuan3D 2.1 is under the Tencent Hunyuan 3D 2.1 Community License, whose territory
    excludes the EU, the UK and South Korea. [Provenance](#provenance) links both.
  - They're on bromigos.org. `bromigos-core` ships the manifests and baked models, and
    the sources stay in this repository.
- **The hologram previews** are offscreen renders of VECTOR's hologram gallery with demo
  readings. They show no likeness, no lab's name and no host names. The lab's readout
  says `LAB`.
  - The worlds' previews, `holo-<model>.jpg` and `holo-<model>-exploded.jpg` in each
    `themes/*/holo/previews/` and `theme/holo/previews/`, are drawn on the world's own
    background colour. They were rendered again on 2026-10-09.
  - The rack's `homelab/holo/previews/holo-rack-isolated.jpg` and the vector repository's
    `assets/holo/previews/holo-*.jpg` are drawn over the packaged empty den
    (`bromigos-den-empty`), with nobody in the chair.
- **The 3D burn-in emblem** (`assets/holo/emblem.holo.npz` in the vector repository) is
  extruded from the Wick theme's emblem SVG by `tools/holo/emblem.py`.
- **The Swarm starship** is made procedurally by `live/tools/make-starship.py`.

### Sounds and voices

- **Sound cues**: blip, chirp, alert, hiss, sweep and signoff. Made with ElevenLabs sound
  effects through nolgia. On bromigos.org, you can click to play them.
- **VECTOR's designed caretaker voices** (`holo/voices/vector-ref-{A,B,C}.wav`). Designed
  from text with Qwen3-TTS VoiceDesign, which is Apache-2.0. No recording was used. They're
  the candidate default voice.
- **The operator's personal voice cast**: four voices designed in Fish Audio from text,
  with references rendered once by `make-refs.py`. They belong to another product, not
  bromigOS. Fish's terms would apply if that ever changed.

### Other assets

- **The Bromigos logos in `brand/`** were traced locally from the canon
  `bromigos-logo.png` with potrace. Their text is set as outlines.
- **The app launcher's icons.** VECTOR's two live in the vector repository's
  `assets/icons/`. The menu's flame is the canonical `theme/emblem/flame.svg`. The others
  are glyphs in the burn-in's ring.
- **The bar's icons** use 1-pixel strokes, in the style of the rest of the bar's set.
- **The peripheral modules** need openrazer, python-evdev and xkeyboard-config's `fkeys`
  option. These are dependencies, not vendored ([peripherals.md](peripherals.md)).

### STATIC, the mascot

- **What ships now: a placeholder.** STATIC's code-drawn rig, faces, Den TV poses and loops,
  and the terminal's pixel head. Every shape is written in `lib/bromigos_static.py` and
  `lib/bromigos_static_term.py` and drawn at run time in the theme's colours. No image
  file or generated pixel ships.
- **What replaces it.** STATIC is being remade in Blender (3D, toon-shaded) and rendered to
  frames. The apps load art by name and height from an art folder's `manifest.json`
  (`lib/bromigos_static_art.py`; BRODEC's `assets/static/manifest.json` uses the same
  schema), so the renders drop in without a code change. Their source, licence and
  renderer get their own row here before they ship.
- **Where the design came from.** The character was designed from concept sheets made on
  the lab with Qwen-Image 2.1 (2026-10-30). The six screen faces BLACKFLAME approved
  (2026-10-31) were redrawn here as pixel grids. Those sheets are under the Qwen Research
  License (non-commercial). They are lab material and are not in this repository.
- **Before anything with STATIC is sold.** The rig is hand-written, but its look follows
  the non-commercial concepts closely. Before a commercial use, such as merchandise, a paid
  app or a store listing, have the character reviewed. If needed, redraw him from a brief
  rather than from the concepts.

### The Drift map's lore catalogue

`live/lore/catalog.json` holds the fields the Drift map reads from bromigos.org's
privacy-checked public lore export, `public/lore/data/lore.json`. It has only the lore
the site publishes, nothing the site leaves out. `tools/lore/sync-catalog.py` copies it.

### Docs and README images

These images in [`docs/images/`](images/) appear in the README and the docs. Each was
resized to WebP for the repository.

- **The render set** (`tools/screenshots/render.py`), drawn offscreen at 2560x1440 with
  demo readings and a made-up lab, resized to 1600 wide:
  - `hero-wick.webp`: the desktop in the Wick, with the bar, the panels and a terminal
  - `widgets.webp`: the panels, cropped from the hero's master
  - `themes-grid.webp`: all eleven themes as the theme switcher previews them, each named
  - `mire-desktop.webp`, `cinder-desktop.webp`: the desktop in Mire and in Cinder
  - `vector.webp`: VECTOR answering on the desk
  - `holo-deck.webp`: the holo deck
  - `menu.webp`: the menu, with a search typed
  - `settings-theme.webp`: Settings on its Theme page
  - `lab-console.webp`: `bromigos lab`, drawn on the tests' recorded lab, not a real one
  - `iso-menu.webp`: the install medium's boot menu, as GRUB draws it in a VM
  - `tidewell-loop.webp`: the desktop in Tidewell, moving. An animated WebP, re-encoded at
    960 wide to keep it under 2 MB
- **Published stills from bromigos.org** (`public/media/` on the site). They're offscreen
  renders of the live layer and the panels (widgets), with demo data.
  - `world-tidewell.webp`, from `world-tidewell`
  - `world-mire.webp`, from `world-mire`
  - `timeline.webp`, from `deck-timeline`
  - `drift-map.webp`, from `map-drift`
  - `screensaver.webp`, from `overlay-screensaver`
  - `panels-cinder.webp`, from `widgets-cinder`
- **Offscreen renders by bromigOS's own test tools.** No faces and no real hostnames.
  - `theme-switcher.webp`: the Customize window on its Themes tab, with all eleven
    themes' previews (each the whole 1920×1080 desktop, drawn in the nested desktop),
    Mire chosen, over the Wick (`tools/screenshots/render.py`, `theme-switcher`: the
    switcher's own renderer, `tools/theme-switcher/render.sh` with
    `BROMIGOS_PREVIEWS_HOLD=1`, in a headless weston), 1600 wide. Redrawn 2026-10-20,
    after kwin 6.8 had cut the previews to their top-left corner
  - `customize-widgets.webp`: the Customize window on its Widgets tab, every widget drawn
    with demo readings (`tools/screenshots/render.py`, `customize-widgets`), 1600 wide
  - `edit-mode.webp`: edit mode on the Wick desktop, NETWORK picked, with the tray
    (`tools/screenshots/render.py`, `edit-mode`: the nested desktop, demo readings),
    1600 wide
  - `settings-idle.webp`, `settings-accessibility.webp`, `settings-updates.webp`: the
    Settings window, with fixture data
  - `boot-menu.webp`, `boot-snapshots.webp`: GRUB's menu and its snapshot list, in QEMU
  - `den-colour-themes.webp`: the den recoloured for the Wick, Cinder and Rime
  - `den-world-colours.webp`: the desktop in Wick · Tidewell and Wick · Mire, each beside
    its world, Tidewell and Mire (`bromigos theme previews NAME --size 2560x1440 --out`,
    drawn from the desktop's pieces with `BROMIGOS_PREVIEWS_NESTED=0`, with demo readings;
    four pictures in a two-by-two sheet), 1600 wide
  - `den-tv.webp`: the den TV playing a test pattern that ffmpeg generates, with its hint
    (`live/tools/offscreen.py bg` with `OFF_TV`, cropped)
  - `den-tv-guide.webp`: The standalone Den TV app, the channel guide, with made-up channels and
    generated stripe posters from a stand-in Jellyfin (`desktop/tests/test_den_tv_guide.py`
    with `BROMIGOS_TEST_SHOTS`, cropped)
- **The README's header emblem** is `themes/wick/emblem/emblem-512.png`, from the Wick's
  emblem kit. It's not copied into `docs/images/`.

### Manual pictures

These images in `manual/src/images/` illustrate the manual. Each shows bromigOS only, with
no likeness and no lab hosts.

- **`den-tv.webp`**, on the Themes and worlds page. The den TV playing a test pattern that
  ffmpeg generates, with its hint, rendered offscreen (`live/tools/offscreen.py bg` with
  `OFF_TV`), cropped. The same picture as the docs'.
- **`den-tv-guide.webp`**, on the Themes and worlds page. The standalone Den TV channel guide with made-up channels and generated stripe posters from a stand-in Jellyfin, drawn in
  a headless weston (`desktop/tests/test_den_tv_guide.py`), cropped. The same picture as
  the docs'.
- **`app-launcher.webp`**, on the Getting around page. The app launcher listing bromigOS's
  own entries, rendered offscreen, cropped.
- **`boot-menu-snapshots.webp`**, on The boot menu page. The installed system's GRUB
  snapshot list in Mire, drawn by GRUB in a VM (the boot menus' run, 2026-10-09).
- **`boot-menu-stick.webp`**, on The boot menu page. The install stick's GRUB menu as
  GRUB draws it in a VM (`tools/screenshots/render.py`, `boot-menu`).
- **`desktop-tour.webp`**, on the Getting around page. The Wick desktop, rendered
  offscreen with demo readings (`tools/screenshots/render.py`, `hero-wick`); numbered
  callouts drawn locally.
- **`desktop.webp`**, on the Welcome page. The Wick desktop, rendered offscreen with demo
  readings (`tools/screenshots/render.py`, `hero-wick`).
- **`driftmap.webp`**, on the Holograms page. The Drift map, rendered offscreen with demo
  readings (`tools/screenshots/render.py`, `driftmap`).
- **`holodeck.webp`**, on the Holograms page. The holo deck, rendered offscreen with demo
  readings (`tools/screenshots/render.py`, `holodeck`); a made-up lab.
- **`hologram-gallery.webp`**, on the Holograms page. The hologram gallery on Mire's stilt
  shack, rendered offscreen; the lab's name in its corner painted out.
- **`lab-console.webp`** and **`lab-job-cancel.webp`**, on The lab console and Your media pages.
  Textual exports from the recorded fake lab (`homelab/tests/test_lab_tui.py`), rendered
  from SVG. The dashboard and the job cancellation question use made-up readings,
  never the operator's desktop or live lab data.
- **`dictation.webp`**, on Dictation. The real dictation panel in a nested Hyprland,
  cropped from `desktop/tests/e2e_dictation_nested.py --shots DIR`, with synthetic audio
  and a made-up transcript. The microphone and audio meter are drawn in code.
- **`media-library.webp`**, **`media-search.webp`**, **`media-channel-picker.webp`**, **`media-channel-membership.webp`** and **`media-delete.webp`**, on The lab console and Your media
  pages. `bromigos media`'s TV and Search tabs, channel picker, membership labels and Delete/Cancel question, exported by its tests
  (`homelab/tests/test_media_tui.py`, `MEDIA_SCREENSHOTS=DIR`) from a fake media stack with
  made-up titles, converted from SVG at 1600 wide.
- **`menu.webp`**, on The menu page. The menu with a search typed, rendered offscreen
  with demo readings (`tools/screenshots/render.py`, `menu`).
- **`screensaver.webp`**, on the Idle and lock page. The screensaver's still from
  bromigos.org (`public/media/overlay-screensaver`), rendered offscreen with demo
  readings.
- **`settings-accessibility.webp`**, on the Accessibility page. Settings › Accessibility
  in the Wick, rendered offscreen.
- **`settings-extensions.webp`**, on the Extensions page. Settings › Extensions in the
  Wick, rendered offscreen (the starter extensions).
- **`settings-idle.webp`**, on the Idle and lock page. Settings › Idle & lock in the Wick,
  rendered offscreen (`bromigos settings --render`).
- **`settings-peripherals.webp`**, on the Keyboards and peripherals page. Settings ›
  Peripherals in the Wick, rendered offscreen (a Razer keyboard's module).
- **`settings-search.webp`**, on the Settings page. Settings searching for "do not
  disturb", in the Wick, rendered offscreen.
- **`settings-shortcuts.webp`**, on the Your own shortcuts page. Settings › Shortcuts in
  the Wick, rendered offscreen.
- **`settings-targets.webp`**, on the Creating with AI page. Settings › Creation targets
  in the Wick, rendered offscreen.
- **`settings-updates.webp`**, on the Updating and rolling back page. Settings › Updates &
  recovery in the Wick, rendered offscreen (an example repository address).
- **`settings.webp`**, on the Settings page. Settings on its Theme page, rendered
  offscreen with demo readings (`tools/screenshots/render.py`, `settings`).
- **`theme-cinder.webp`**, on the Themes and worlds page. The desktop in Cinder, rendered
  offscreen with demo readings (`tools/screenshots/render.py`, `theme-cinder`).
- **`theme-switcher.webp`**, on the Themes and worlds page. The Customize window on its
  Themes tab over the Wick, with all eleven themes' previews and Mire chosen, rendered
  offscreen with demo readings (`tools/screenshots/render.py`, `theme-switcher`). The
  same picture as the docs'.
- **`customize-widgets.webp`**, on the Themes and worlds page. The Customize window on its
  Widgets tab over the Wick, rendered offscreen with demo readings
  (`tools/screenshots/render.py`, `customize-widgets`). The same picture as the docs'.
- **`edit-mode.webp`**, on the Panels page. Edit mode on the Wick desktop, NETWORK picked,
  rendered offscreen in the nested desktop with demo readings
  (`tools/screenshots/render.py`, `edit-mode`). The same picture as the docs'.
- **`themes-grid.webp`**, on the Themes and worlds page. The eleven themes as the theme
  switcher previews them, rendered offscreen with demo readings
  (`tools/screenshots/render.py`, `themes-grid`).
- **`timeline.webp`**, on the Holograms page. The timeline deck, rendered offscreen with
  demo readings (`tools/screenshots/render.py`, `timeline`); demo history.
- **`vector.webp`**, on the VECTOR page. VECTOR answering on the desk, over the Wick,
  rendered offscreen with demo readings (`tools/screenshots/render.py`, `vector`); a
  made-up lab.
- **`world-mire.webp`**, on the Themes and worlds page. The desktop in Mire, rendered
  offscreen with demo readings (`tools/screenshots/render.py`, `world-mire`).
- **`world-tidewell.webp`**, on the Themes and worlds page. The desktop in Tidewell,
  rendered offscreen with demo readings (`tools/screenshots/render.py`, `world-tidewell`).

## Provenance

On 2026-10-08 the operator cleared every bromigOS and brand asset to ship and to show on
bromigos.org, except the bare-face likeness art above. In his words: "all of our assets
should be totally fine. We did all of the correct ways to generate them."

The site doesn't caption the art as AI-generated. This file records how each piece was
made. For reference, here are the terms each provider published, as read on 2026-10-08:

| Model (route through nolgia) | Terms |
|---|---|
| gpt-image-2.5-flare (OpenAI API) | <https://openai.com/policies/services-agreement/> (updated 2025-12-01), <https://openai.com/policies/sharing-publication-policy/> (updated 2022-11-14) |
| minimax-h3 (MiniMax Open Platform API) | <https://platform.minimax.io/protocol/terms-of-service> (effective 2026-03-30) |
| remove-background (Bria, through fal) | <https://fal.ai/legal/terms-of-service> (updated 2026-09-08); Bria's background-removal terms (September 2026 v1.5, from Bria's Legal Lobby) |
| hunyuan3d-v3 (Tencent, through fal) | <https://www.tencentcloud.com/document/product/301/78149> (updated 2026-03-10), <https://www.tencentcloud.com/document/product/301/74049> |
| seedream-4.5, seedance-1-5-pro (BytePlus, through OpenRouter); seedance-2.5 (through SeeGen) | <https://openrouter.ai/terms> (updated 2026-08-31), <https://docs.byteplus.com/en/legal/docs/service-specific-terms>, <https://seegen.ai/terms-of-use> |
| Hunyuan3D 2.1 (local) | <https://huggingface.co/tencent/Hunyuan3D-2.1/blob/main/LICENSE> |
| Qwen-Image-2.1 (local) | <https://huggingface.co/Qwen/Qwen-Image-2.1/blob/main/LICENSE> |
| SeedVR2 7B (local, int8 weights from Comfy-Org/SeedVR2) | <https://huggingface.co/ByteDance-Seed/SeedVR2-7B> (Apache-2.0) |
| ElevenLabs sound effects | <https://elevenlabs.io/terms-of-use> (2026-03-31), <https://elevenlabs.io/sound-effects-terms> (2026-02-12) |
| nolgia itself | <https://nolgia.ai/terms> (updated 2026-10-08) |

The local processing tools, Depth Anything V2, SAM, LaMa and BiRefNet, are open-weights
models used to split and cut the paintings.

- **Den TV launcher icon** (`theme/app-icons/*/apps/bromigos-den-tv.svg`): **yes**.
  Drawn in code by `theme/tools/build-app-icons.py`, like the other launcher icons.
  A TV outline and play glyph; no outside art.

- **Text console login banner** (`settings/console/60-bromigos.issue`): **yes**.
  Original ASCII text and frame, drawn for bromigOS. No outside art or patched font.

- **mehshell prompt wordmark and width data**: **yes**. The `bromigOS` wordmark is
  plain original text. Unicode 17 East Asian Width ranges use Unicode License V3;
  mehshell's package includes the upstream `LICENSE-UNICODE` notice.
