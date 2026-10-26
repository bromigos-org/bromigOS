# Changelog

Every change to bromigOS and VECTOR, release by release: the technical log, made from the commit
subjects by git-cliff (tools/release/cliff.toml) when a release is prepared (docs/release.md).
What a release means for the people using it, in plain words, is the manual's What's new
(manual/src/whats-new.md).

This repository's history starts at 0.1.2. The commits before it, which the links in the
0.1.2 section and below name, are in the archives, `bromigos-org/bromigOS-archive` (and
VECTOR's, `bromigos-org/vector-archive`).

<!-- releases: tools/release/release.py adds each release below this line, newest first -->

## [0.1.3] - 2026-10-26
<!-- release: 0.1.3-rc1 -->

Release candidate v0.1.3-rc1.

Since v0.1.2. In plain words: the manual's What's new (manual/src/whats-new.md).

### Core (the bromigos command)

- install: a --with package no synced repository has comes from the AUR with the helper (1password on the public mirror) ([9df93cb](https://github.com/bromigos-org/bromigOS/commit/9df93cb74bff601de016bfa6d90b4d987395a21c))
- setup answers: an [extensions] install entry can be a table, { source, path, ref }, for an extension in a folder of its repository ([079e510](https://github.com/bromigos-org/bromigOS/commit/079e510f3f12c57f9f31a5cd7d5dd21d4df5ae0a))
- migrations: machines installed from the first v0.1.2 ISO move from the r2.dev address to pkgs.bromigos.org ([2a3b405](https://github.com/bromigos-org/bromigOS/commit/2a3b405d03b0be619eca549a79a62d8933b82187))
- core: cargo fmt on snapshot.rs (it failed cargo fmt --check) ([516eb26](https://github.com/bromigos-org/bromigOS/commit/516eb26313c38d2b1b7d70588a25e23aeb9f55a9))
- setup: the first-run Homelab question offers Find my lab, and Settings › Lab has a Find my lab… button ([2b42a31](https://github.com/bromigos-org/bromigOS/commit/2b42a31ff951e0d978ad4d2c5e0d8b3d4cbc3f7c))
- update: before the transaction, say to answer y when oo7 takes gnome-keyring's place ([6fbac7f](https://github.com/bromigos-org/bromigOS/commit/6fbac7fdd53c5f39346443bcf9054b4209c1f0f0))

### Desktop

- desktop: the den TV's keys (Super+Alt+P full screen, Super+Alt+. and , channel, Super+Alt+M sound), and e2e_tv_nested.py: the TV in a nested Hyprland with a fake Jellyfin and a PipeWire nobody hears ([c2dd6fd](https://github.com/bromigos-org/bromigOS/commit/c2dd6fdcdc201023ded4bb3182918737c17789d5))
- settings: a widget's sign-in lists each account, with Add another account… and Remove ([8dd3506](https://github.com/bromigos-org/bromigOS/commit/8dd3506cca896fc92d6c3f4dc61e46e89f6d7324))
- settings: Den TV, the channel guide: every channel on every screen as a TV guide (now, next, poster, progress, on air), Add channel (a library, picked shows, YouTube, a folder, downloaded YouTube), remove with Undo, drag to reorder or onto another screen, rename, Tune now ([9f6fb72](https://github.com/bromigos-org/bromigOS/commit/9f6fb72687489a42d32dc7d6b253f1baaedb7e4b))
- desktop: add game mode and bridge legacy tray icons ([d1729b1](https://github.com/bromigos-org/bromigOS/commit/d1729b121ab067fd614e10750974f6f590687229))
- settings: Account has an optional Bromigos account row: sign in, sign in with an SSH key, sign out ([9eb7eca](https://github.com/bromigos-org/bromigOS/commit/9eb7eca402606aac8d36aa722e15fef20a9e04e5))
- desktop: the keyring comes with the desktop: oo7, gcr's password window and libsecret, oo7's daemon in every session ([db4adf7](https://github.com/bromigos-org/bromigOS/commit/db4adf7a5569a6776440d14f2fb8e0c5e961ea2f))

### Live layer

- live tests: the private-names check no longer flags VECTOR's public tool names (k8s_restart, k8s_scale, k8s_delete_pod, k8s_run_job); k8s_<share> names stay caught ([75058e7](https://github.com/bromigos-org/bromigOS/commit/75058e738775940582ce14b6acaff356562cb43c))
- live: the den TV: channels from Jellyfin, Plex, YouTube or files on the den's screens after each one's own picture, played by libmpv into a texture in the screen's glass (curve, scanlines, glow, the den's tint), paused when it can't be seen; the hover hint, the wheel, full screen with sound in mpv at the same moment, sound through PipeWire (muted with bromigOS, ducked for VECTOR, silent when locked); bromigos-live tv; the den pixel for pixel as before with no media channel on; a locker only counts for its own Hyprland ([df6b97c](https://github.com/bromigos-org/bromigOS/commit/df6b97c0a2997addfab8c1ee26a751c8ca2f2cb9))
- live: keep the static wallpaper only as a fallback ([fd704e1](https://github.com/bromigos-org/bromigOS/commit/fd704e14b2ad863b800764afec13d7d1e73a3b50))
- live: hand over the wallpaper after the first frame and answer ownership promptly ([666be82](https://github.com/bromigos-org/bromigOS/commit/666be82a47fd0ad4d1048567cf296dd1d9cb03cb))
- live: remove the still as soon as the background paints its first frame ([bf8bdc5](https://github.com/bromigos-org/bromigOS/commit/bf8bdc50ae3c360b5f4657b578340ddafbd895d5))
- live: refresh every surface when the palette changes ([262369a](https://github.com/bromigos-org/bromigOS/commit/262369a6f340139524bb49f9c747c9a63a42ea5d))
- live: use palette tokens for scanners, HUDs and shader colours ([fc59106](https://github.com/bromigos-org/bromigOS/commit/fc59106015eafebcc81b81fd40d499d4900721e6))
- live: read actor colours without importing OpenGL ([3bab68f](https://github.com/bromigos-org/bromigOS/commit/3bab68f43ea0ebff8887a735053c51ce83900a1c))
- live, media: den TV knobs, on-demand playback and number-pad remote ([bc77971](https://github.com/bromigos-org/bromigOS/commit/bc779713264ed4d3a67dbaac05c6329514c1f1c4))
- live: install the den controller's headless test dependencies ([64b56e8](https://github.com/bromigos-org/bromigOS/commit/64b56e8dfe307b9a46ca9a75c24f8c9304f982fc))
- live: clear den knob readouts when the pointer leaves ([163c514](https://github.com/bromigos-org/bromigOS/commit/163c5143152aeecba7491ee9095c0c75f371c060))
- live: wait for the null player's worker before test cleanup ([c6af216](https://github.com/bromigos-org/bromigOS/commit/c6af216be77b398fb048aef126da15b8cb2e0ee1))
- live: show the mute glyph on every den TV control path ([08c04c1](https://github.com/bromigos-org/bromigOS/commit/08c04c1da10911a56cbe4264abedf4776dada67a))
- live: remove the den TV equipment controls ([f2486e0](https://github.com/bromigos-org/bromigOS/commit/f2486e0cf7cbaa310d4c570d790a4de8a979b69f))
- live, widgets: add Skip to the TV hover menu and MEDIA remote ([670a266](https://github.com/bromigos-org/bromigOS/commit/670a266eb0554f50cae10afe1eeabdd34e74a117))
- live: keep notification cues quiet during game mode ([88bafec](https://github.com/bromigos-org/bromigOS/commit/88bafecd1f7f13a64f49e6cf4a1c541ff915e9a5))

### Boot and the ISO

- iso: the medium installs with no network; a release's ISO names the public mirror and is checked ([85fc5cf](https://github.com/bromigos-org/bromigOS/commit/85fc5cf64551a303b737fb2733a2a862792e56d3))

### Widgets

- widgets: edit mode (drag to move, a corner to resize, × to hide, snapping to an 8 px grid and the other panels' edges with guides, undo, keyboard-only editing) and the widget gallery in its tray; every panel says its description, category, what it reads and its sizes; layout.json written in one step through a dotfiles symlink ([ff0c197](https://github.com/bromigos-org/bromigOS/commit/ff0c197020bafad79889ec492f7146f5fb70fdd5))
- widgets: size classes (compact, standard, wide, tall, large): a panel declares sizes and default_size, lays out for size_class(w, h); edit mode resizes freely inside a class and snaps between them; a size picker on the gallery's cards, Add to desktop at the default class, bromigos panels size NAME CLASS, render --size ([59284c0](https://github.com/bromigos-org/bromigOS/commit/59284c00acae3708afca58e2919839c863a1e2b7))
- widgets: a layout for every size class of every panel: SYSTEM large with each thread's history and the busiest processes, NETWORK wide and large with the last hour and its connections, WEATHER's hourly strip and week, STORAGE's reads and writes, WORKBENCH's commits, SHORTCUTS in columns, CONNECTIONS tall, and LAB large with the constellation hologram (10 fps while shown, still with reduced motion); each reads more only while it's shown ([250f5cf](https://github.com/bromigos-org/bromigOS/commit/250f5cf17cc9840d6eefe26bdc69481301946854))
- widgets: Panel.available(): a panel that can't show anything here (no source configured) isn't offered in the gallery, and is greyed out with the reason while it's on the desktop; asked once per opening ([88e4507](https://github.com/bromigos-org/bromigOS/commit/88e450730fc13f3abc9d0bb9a19d9e1ff2e94ffe))
- widgets: a plugin's wake() redraws its panel at once: the window holds a SafePanel around the plugin, which wakes with its own instance (plugins.same_panel) ([8fa0c20](https://github.com/bromigos-org/bromigOS/commit/8fa0c2003b010482c4d02a6d431e938db9d4fb9f))
- widgets: a widget's own settings: a panel lists its fields (text, list, number, bool, choice, secret-signin), reads them with self.setting(key) from ~/.config/bromigos/widgets/<name>.toml (re-read when it changes; written in one step through a symlink); Settings draws the form, with sign-ins through bromigos_account (the code, Copy, Open the page, a countdown; Connect <service>; a GitLab token); bromigos panels settings|set|unset ([93fe591](https://github.com/bromigos-org/bromigOS/commit/93fe59130691c0fe7d9a1cc66f888b10f458a1d8))
- widgets tests: SHORTCUTS gets a fixed set of binds in the layout test, so its size classes are checked in a clean home (a package build) too; the whole suite passes with an empty HOME ([a2f7293](https://github.com/bromigos-org/bromigOS/commit/a2f729375eb0485a8cfd590b9b33c5f92bee5fc0))
- widgets: the built-in plugin panels' kit (settings in widgets/<name>.toml, polling that pauses while a panel is hidden, empty states, buttons, pictures) and lib/bromigos_account.py, the sign-in helper widgets share: the device flow, PKCE on a loopback redirect, tokens in the keyring through libsecret; `bromigos account` ([6e97d45](https://github.com/bromigos-org/bromigOS/commit/6e97d45ff6eab213acd3005646254a24983688af))
- widgets: GPU, a built-in panel: load, video memory, temperature, power, clocks and each process's use through NVML; AMD and Intel from /sys/class/drm, saying what their drivers don't give; ten minutes of history when large ([ea8b91c](https://github.com/bromigos-org/bromigOS/commit/ea8b91c13019378acac090fb15235c3897eb933a))
- widgets: NOW PLAYING, a built-in panel: any MPRIS player's track, cover and position, with previous, play/pause, next and seek; a cava visualizer only while something plays, the panel is seen and motion is full ([b9ca2ba](https://github.com/bromigos-org/bromigOS/commit/b9ca2baa78a303f9d8a017d44e6eadc909c74bf4))
- widgets: SPOTIFY, a built-in panel: what your account plays on any device, the queue and recently played, signed in with PKCE through the account helper; transport through MPRIS when the Spotify app is here, else the Web API ([1a55895](https://github.com/bromigos-org/bromigOS/commit/1a558951a07490d3108ec3710f08d050f4a7c88d))
- widgets: every built-in plugin panel is checked for its gallery words and size classes that don't overlap; the sign-in empty state opens with what the panel reads ([77e7003](https://github.com/bromigos-org/bromigOS/commit/77e700373cbecc19599230d8f4509f32237fc4b5))
- widgets: UPDATES, a built-in panel: repository and AUR updates waiting, migrations, what needs a restart or a reboot, and the last updates with their snapshots, from bromigos update --check --json at most every 3 hours while it's seen; Update runs it in a terminal ([a06789c](https://github.com/bromigos-org/bromigOS/commit/a06789c007ae474a43265d26c14e7225617d8040))
- widgets: VECTOR, a built-in panel: his state, the emergency switch (off at once, on only after a YES), his recent tool calls from his audit log with argument values never shown, and his pull requests waiting for your review ([5dad122](https://github.com/bromigos-org/bromigOS/commit/5dad1227110b33836ca7b819fb494927df6d45a0))
- widgets: CI & PRs, a built-in panel: the build-status board for the repositories you list (each default branch's checks and recent runs) and the pull requests waiting on you, in one GraphQL query every 3 minutes through gh ([af59d13](https://github.com/bromigos-org/bromigOS/commit/af59d1378441a833231b2a435ba2780ca6f9092a))
- widgets: TWITCH, a built-in panel: your channel live or not (viewers, title, category) and the channels you follow that are live, each a click away, signed in with the device flow; large adds the stream's picture and chat activity (a count, never the text) from Twitch's anonymous chat; bromigos_account.refresh() ([4ea368f](https://github.com/bromigos-org/bromigOS/commit/4ea368f397a1876b68ec730bbb8ed657713218b7))
- widgets: DISCORD, a built-in panel: who's online in a server, from its invite or its server widget, with no token; the members, their status and voice channels when the widget is on, and the online count over time ([d5dfa9b](https://github.com/bromigos-org/bromigOS/commit/d5dfa9baedb44ca8b061fa38522db65402d6338a))
- widgets: YOUTUBE, a built-in panel: a channel's latest videos and whether it's live, with no API key (bromigos_youtube when it's there, else the channel's feed and its live page); thumbnails when large ([6a29cdf](https://github.com/bromigos-org/bromigOS/commit/6a29cdfbe6047701404d46d2aa2903b81e5a2cfe))
- widgets: a built-in plugin adds its folder after the standard library and installed modules, so a panel's file name never hides one; an account with a pasted token needs no client ID ([052d44e](https://github.com/bromigos-org/bromigOS/commit/052d44ec3c849ddc21bbeabbaddbe9ae1a4a4bd4))
- widgets: CALENDAR, a built-in panel: today's and the coming days' events from ICS addresses (a CalDAV server's export, webcal), local .ics files and vdirsyncer folders, with repeats expanded; an agenda when tall and a week's hour grid when large; no sign-in ([956b9ec](https://github.com/bromigos-org/bromigOS/commit/956b9ec67820722db1045f519dfbaaeb70da2efc))
- widgets: GITHUB, a built-in panel: your personal feed (notifications, reviews asked of you, what's assigned to you, your repositories and their stars, their activity) and your contribution graph when large; your gh login, else the device flow ([39f754c](https://github.com/bromigos-org/bromigOS/commit/39f754c2e70f8e1caf88a9a8ce0bb4055d391d32))
- widgets: GITLAB, a built-in panel: merge requests assigned to you or asking for your review, your to-dos, and your projects' pipelines, on gitlab.com or your own instance; the device flow or a personal access token ([2f72adf](https://github.com/bromigos-org/bromigOS/commit/2f72adf075752fcfaf9683b73ad4e9fe41bab86e))
- widgets: the built-in panels read their settings through widget_settings (what Settings' form writes); bromigos_account.sign_in takes cancelled as a callable or an Event; the plugin tests decide demo readings themselves ([4b6360e](https://github.com/bromigos-org/bromigOS/commit/4b6360e96bd5a639b8549083e2e89861d9396af8))
- widgets: MEDIA, a built-in panel: the den TV's now and next, continue watching and recently added with posters; its settings make a TV channel (a library, collection or playlist the servers offer, or YouTube); offered only with a media source ([1eec912](https://github.com/bromigos-org/bromigOS/commit/1eec912078815d26cb96685b8e26a1417add0148))
- widgets: each panel on any monitor. layout.json keeps a panel's own monitor ("output": make, model and serial, the connector as the fallback) and is version 2; edit mode puts a canvas on every monitor, a drag over a monitor's edge moves the panel there, and the tray's Monitor list sets the picked panel's; an unplugged monitor's panels stand in on the primary (their own place kept and saved) and go back when it returns; an old single-monitor layout is migrated when the panels start, written through its symlink. bromigos panels monitor puts every panel on one and forgets each one's own. Tests: arrange's monitors and migration, the CLI, and the nested e2e with a second output ([db520ca](https://github.com/bromigos-org/bromigOS/commit/db520ca255aecbcb4b1ca4732070ccc926324181))
- widgets: category buttons from what the widgets declare everywhere. gallery.categories() makes them (bromigOS's in order, then any other a widget names, each with its word, a hint and how many widgets it holds) for edit mode's tray, and `bromigos panels gallery` hands them to Customize's Widgets tab and Settings › Widgets, which draw them with one helper (widgetform.category_buttons); the fixed six lists are gone. Tests: a widget of your own in a new category gets a button ([1518fd8](https://github.com/bromigos-org/bromigOS/commit/1518fd8d5e0e9c98e0cfc11d434c7437c5666845))
- widgets: one panel shows several accounts, rows merged and tagged ([b53089c](https://github.com/bromigos-org/bromigOS/commit/b53089ca68f3bc37e810b43a520f77625dd45a12))
- widgets: layouts (Minimal, Developer, Homelab, Streamer, Media, Gamer, Everything, and each theme's own), Tidy up, and never stacking a widget on another ([9988b0f](https://github.com/bromigos-org/bromigOS/commit/9988b0f94d0b050686b2138359182898bd68efb1))
- widgets: a layout counts an account widget as signed in when any of its accounts is (several accounts per service) ([5e21783](https://github.com/bromigos-org/bromigOS/commit/5e21783d657f69ad86f28e97412ebc6d8aa8b66a))
- widgets: VECTOR's panel asks his daemon whether he's running, as `bromigos vector status` does ([97e81a1](https://github.com/bromigos-org/bromigOS/commit/97e81a131d501a171c28462f9c0ea88e58d63494))
- widgets: panels fit their content and never cut it off; a bigger panel pushes its neighbours aside, never onto the scene ([70d4d31](https://github.com/bromigos-org/bromigOS/commit/70d4d3162df477325e2c39d7933131d2b5a65e79))
- widgets: make the missing calendar dependency test deterministic ([a720167](https://github.com/bromigos-org/bromigOS/commit/a720167a5ae69bed236a5f9539f47ffa5785c9c7))
- widgets: restore the visible set and fit panels to their actual frames ([b72c234](https://github.com/bromigos-org/bromigOS/commit/b72c234a8dfa804237749bdcf4f476c3ea160023))
- widgets: open the standalone Den TV app from the media remote ([60cd077](https://github.com/bromigos-org/bromigOS/commit/60cd077ecf6d845f0298d620e3e24ab6e5e0b661))
- widgets: add optional storage display names ([a4d9959](https://github.com/bromigos-org/bromigOS/commit/a4d99592b61e82ca4376edfbb66b7127e25ac26a))
- widgets: keep storage display names on one line ([5c9cd5f](https://github.com/bromigos-org/bromigOS/commit/5c9cd5f9277ee67af1d731843bb77b0404ab0d19))
- widgets: VECTOR panel test no longer races the panel's own daemon poller ([6da8a85](https://github.com/bromigos-org/bromigOS/commit/6da8a85d0cc08815777eb6e531784af8366020ef))
- widgets: LAB draws a null CPU or memory reading as 0% instead of failing (five failures in a minute had switched the panel off) ([f9f51aa](https://github.com/bromigos-org/bromigOS/commit/f9f51aa15136fd02ad2b49903ccaeaf57c921f48))
- widgets: a monitor switched off and on again puts every panel back where it was, not where the smaller stand-in squeezed it ([1b8f68c](https://github.com/bromigos-org/bromigOS/commit/1b8f68cb9dda8cdaa985ec84519b59d296706bcf))

### Themes and art

- theme cards: an older preview's hint says "A newer preview is on its way"; with previews held, the finished state; theming.md says how an older preview is marked ([183fb93](https://github.com/bromigos-org/bromigOS/commit/183fb93afd1fee0c59c2ee65f4a05ba955d7c788))
- theme: colour Zettlr in every theme ([15d2264](https://github.com/bromigos-org/bromigOS/commit/15d2264b4632b71023d95f2fd53a0875158c5287))
- themes: Wick · Tidewell and Wick · Mire, the den in the two worlds' colours ([c11e973](https://github.com/bromigos-org/bromigOS/commit/c11e973b2b09fde1e7d5e2b4c0a20a2bc1edf0a1))

### Homelab

- homelab: the energy capability and an enphase adapter (an Envoy's production.json, with a token for firmware 7 and later), a minecraft adapter for games (Server List Ping: players, version, message of the day), and a link to each alert's detail ([415c53c](https://github.com/bromigos-org/bromigOS/commit/415c53ca9f01c925933ccaba58e213ebf612d72c))
- homelab: SOLAR, a widget: what the panels make, what the house uses and what goes to or from the grid and the battery, from the energy capability; a power-flow picture and the day's curve when large ([8f9c5e1](https://github.com/bromigos-org/bromigOS/commit/8f9c5e14c3ca0b4e0bcc6a721a9cb20b8bae150d))
- homelab: GAME SERVERS, a widget: each game server's status and players (Pelican, Minecraft), with the names of who's on when large ([8ea2e24](https://github.com/bromigos-org/bromigOS/commit/8ea2e24b001f5b6bdcb14662ee13692b671b2003))
- homelab: ALERTS, a widget: firing and pending alerts, worst first, each a click away from its detail; counts by severity and the last 24 hours when large ([3330706](https://github.com/bromigos-org/bromigOS/commit/33307069b1a47fa35edc78576b893ea04855a2c4))
- homelab: LAB JOBS, a widget: the lab job queue's running job and its progress, what waits and why, the GPU's free memory, and what finished; the last six hours when large. Each homelab widget appears only when its source is configured ([f0b2c38](https://github.com/bromigos-org/bromigOS/commit/f0b2c381ad4f79de0aa810f79e35e7e6a522176f))
- homelab: Pinchflat, the YouTube downloader: an adapter (sources, newest videos, the download queue, failed jobs), the youtube-downloader capability, the console's YouTube downloads card, and bromigos lab youtube sync ([357b6d5](https://github.com/bromigos-org/bromigOS/commit/357b6d5b9ed566c49e0994af106060cdf34dd2c1))
- homelab: the Storage card names the NAS behind each share and shows its free space ([29583f9](https://github.com/bromigos-org/bromigOS/commit/29583f9ad977251b0b34eaf0fd8c481fca3019e0))
- lab catalog: Plex and Pinchflat in the media group, configure steps, and a Storage step (use the NAS you already have) ([be01340](https://github.com/bromigos-org/bromigOS/commit/be013408cc739d19d22f0d12fe27ebb606c84346))
- homelab: the video capability: a Jellyfin or Plex server's libraries, collections and playlists, their items, continue watching, recently added, a stream (direct, or an H.264 transcode over direct_max_mbps) with the key in a header, the web page and the poster; tested against fake servers ([756b316](https://github.com/bromigos-org/bromigOS/commit/756b3164e15a77ffc84354527ac42769776431f2))
- homelab: bromigos lab youtube add|list|remove|pause|resume|refresh|status|quality|cookies: Pinchflat without its web page, driven through its own forms (GET the page, its CSRF token and session, POST it back; pinned to v2025.9.26, and a changed form stops before anything is sent). add picks the profile from the URL, --since, --name, --quality best|2160p…480p|audio (a "<profile> · <quality>" copy made from Pinchflat's own template form, reused after); remove asks first and keeps the files unless --delete-files; quality changes new downloads only; cookies set|clear|status keeps a Netscape cookies.txt in a Vault field or a file and turns each source's Cookie Behaviour to When Needed, never showing a value; [youtube] quality is the lab's default; --json on each. The YouTube card's "Add a channel or playlist…" in the lab dashboard (key a) runs the same code. The adapter takes user_ref beside auth_ref, and reads the route token from the Sources page when the basic auth is set. Tests: a fake Pinchflat built from pages recorded read-only from a real one (no host, tokens or lab names), every command, the CSRF check, the form-changed stop, the dashboard form. Docs: the manual's Lab and Homelab pages (disk space per hour, measured), docs/lab.md and docs/homelab.md ([bef9e84](https://github.com/bromigos-org/bromigOS/commit/bef9e84f3ce6ebb0510e00ddaab0f73da4c64f17))
- homelab tests: the cert-manager metrics test reads the fixtures' clock, not the real one (it failed once the fixed "now" was two days old) ([8161aa0](https://github.com/bromigos-org/bromigOS/commit/8161aa0a0758a3e71ba5e833aefbc503e7b92a84))
- homelab: bromigos lab media search|get|status|upcoming|recent|language|calendar: ask the lab's media stack for films, shows, anime and music at the best quality its profiles allow, in your languages ([c41460f](https://github.com/bromigos-org/bromigOS/commit/c41460fe9fbcebc873d8c9bd8280054bf5c159ea))
- homelab: bromigos media: the media library in a terminal (TV, movies, music, YouTube, downloads, upcoming, add), with monitor, profile, search now, open, play and delete ([b55e30a](https://github.com/bromigos-org/bromigOS/commit/b55e30a1c89f09c81ebce1c8248b3658ddbe6cbd))
- homelab: media status: a download whose time left is over 30 days is stalled (no seeds or no speed), not "587 d left" ([3580366](https://github.com/bromigos-org/bromigOS/commit/358036600cb8d1b86262cd275e45ad909c00f459))
- lab: provision Core and Advanced through reviewed repositories ([71bd8eb](https://github.com/bromigos-org/bromigOS/commit/71bd8ebb0b43bb867bc03e9c5e32a7c88b05312e))
- homelab: provision agents against an existing model endpoint ([7081951](https://github.com/bromigos-org/bromigOS/commit/7081951b578a175377a3c05f5c4679a86bd60651))
- lab: provision owned VMs, grow k3s clusters and install monitoring ([7d66846](https://github.com/bromigos-org/bromigOS/commit/7d6684624ee837807a2ac293a5131dd4d3f45853))
- lab: ship the standalone console and publish tested source releases to AUR ([a10f06c](https://github.com/bromigos-org/bromigOS/commit/a10f06c1632ad7a484ca40a26927db59f46e2ba4))
- lab catalog: weekly refresh 2026-10-12 (metadata and pending review entries) ([acb5e1e](https://github.com/bromigos-org/bromigOS/commit/acb5e1e04cb647f5ade250fe4e831062a2a34b2c))
- lab: add reviewed rack maintenance checklists and journals ([347512f](https://github.com/bromigos-org/bromigOS/commit/347512fde1b91e4e1b40ea2fc9d1e2e704d0ba06))
- lab: monitor PDU outlets and review named Ansible power plans ([4633187](https://github.com/bromigos-org/bromigOS/commit/4633187afe035e74e914fb8ecf5ad938c087839d))
- lab: recognize the alternate PDU Pro model identifier ([b29b61f](https://github.com/bromigos-org/bromigOS/commit/b29b61f42fdf387839413ec3e49a37e3bbc31134))
- lab catalog: weekly refresh 2026-10-19 (metadata and pending review entries) ([ee2b6a9](https://github.com/bromigos-org/bromigOS/commit/ee2b6a933288a60534a05138e2f4071c275a2cc9))
- lab: bromigos lab provision with no arguments walks a new user through setting up a spare box, and the plan says what hardware the box has ([c705f8b](https://github.com/bromigos-org/bromigOS/commit/c705f8bb429b04a83b401a3f4822c334674aef5e))
- lab: Find my lab finds the devices this computer and the lab already know, and checks only those (bromigos setup homelab --find) ([703f77e](https://github.com/bromigos-org/bromigOS/commit/703f77e50412cb360b65548f1a836959d67b2bae))
- lab: the guided setup's box step offers the machines Find my lab found that answer SSH, with "Type an address" kept ([6a2ab84](https://github.com/bromigos-org/bromigOS/commit/6a2ab84fb331d441a7878ef487c5bbbbf3ed20a0))
- lab: a provisioned box announces _bromigos-lab._tcp over mDNS, so Find my lab always finds it ([89a61d6](https://github.com/bromigos-org/bromigOS/commit/89a61d6e5999f175616b7d6173ff435776412f60))
- lab: provisioning offers the Bromigos account's SSH keys for the new box's authorized_keys ([26459fb](https://github.com/bromigos-org/bromigOS/commit/26459fbca17d187f3e823bf61eba752be4e5f5be))

### VECTOR

- vector: SUPER+ALT+C reads Claude Code's replies aloud as they finish (VECTOR's follow mode), with ◉ READING CLAUDE on the bar and a menu entry ([273a485](https://github.com/bromigos-org/bromigOS/commit/273a4853d2c04cd11bb08a4e34b45abc0ba659ac))

### Docs

- docs: CODE_OF_CONDUCT.md (Contributor Covenant 2.1, contact@bromigos.org), linked from the README and CONTRIBUTING.md ([ebea325](https://github.com/bromigos-org/bromigOS/commit/ebea32571140975bfcdec9133b4c5dfa4571a02c))
- docs: a release's ISO (how it's built, checked, tested, signed and attached), and v0.1.2's run ([ba15dab](https://github.com/bromigos-org/bromigOS/commit/ba15dab4c67b53e18a18fb1ecdff9bacdd040f3b))
- docs: edit mode, the widget gallery, adding a widget, and what a panel tells the gallery; the manual's Arrange the panels and Choose panels; Super+Alt+W in the key table ([3a2c5ad](https://github.com/bromigos-org/bromigOS/commit/3a2c5ad30c1cfe921321cf90e0d1d0177620d040))
- docs: a panel's settings in widgets/<name>.toml, the built-in panels' kit, and a widget that needs an account (lib/bromigos_account.py, `bromigos account`); libsecret for the widgets' sign-ins ([1afe746](https://github.com/bromigos-org/bromigOS/commit/1afe746c68eac4a1ead789689dfa704ba1d7e2b0))
- docs: the built-in widgets (GPU, UPDATES, VECTOR, CI & PRs, GITHUB, GITLAB, CALENDAR, NOW PLAYING, SPOTIFY, TWITCH, YOUTUBE, DISCORD, and the homelab's LAB JOBS, SOLAR, GAME SERVERS, ALERTS), each one's setup; the manual's panels that need an account; the energy capability, the enphase and minecraft adapters; bromigos account in the command reference ([056e305](https://github.com/bromigos-org/bromigOS/commit/056e3057c12d6fe2cd1049587e9d7589606771af))
- docs: YouTube downloads in the lab console (the card, bromigos lab youtube and its sync, the pinchflat source) and the Storage card's NAS and free space; the manual's Lab and Homelab pages too ([9027921](https://github.com/bromigos-org/bromigOS/commit/9027921251e6f249b61ad3a5f8d8294704ee4459))
- docs: Customize, its two tabs and their tools (theming.md, widgets.md, desktop.md, menu.md, the manual's Themes and worlds and Panels) ([af42ae3](https://github.com/bromigos-org/bromigOS/commit/af42ae3b0caffdbcc863cc1392b9a604dad95ada))
- docs: the den TV (live/README.md, ELEMENTS.md, the manual's Themes and worlds, Panels, keys and glossary), the video capability and video libraries (homelab.md), the MEDIA panel (widgets.md), bromigos_tv and bromigos_youtube (lib/README.md) ([2aa26f4](https://github.com/bromigos-org/bromigOS/commit/2aa26f485924d56983b69068a30ff60a06fc73a6))
- docs: the den TV's measured cost ([db87846](https://github.com/bromigos-org/bromigOS/commit/db878461457448b768a2d551bb9f464cbdd73a1f))
- docs: pictures of the Customize window on its Themes tab (theme-switcher.webp, docs and manual) and its Widgets tab, and of edit mode, in widgets.md, theming.md and the manual's Panels and Themes and worlds pages; each in ASSETS.md. Drawn offscreen with demo readings by tools/screenshots/render.py (new shots customize-widgets and edit-mode; the switcher's previews held); the switcher's --screenshot waits for its first frame instead of failing now and then ([cd105e1](https://github.com/bromigos-org/bromigOS/commit/cd105e1ad17b7a15e606ce9f337e26f8410455ec))
- docs: v0.1.2's ISO names pkgs.bromigos.org and is public; when the r2.dev address can go ([b9ba196](https://github.com/bromigos-org/bromigOS/commit/b9ba196fedafa87e8b3d1fc69b41650679e40bae))
- docs: the secrets command is `bromigos secrets sync` (bromigos-secrets is internal, in /usr/lib/bromigos/bin) ([8283f2d](https://github.com/bromigos-org/bromigOS/commit/8283f2d476229786b5b86ca224d5076387c4b2d8))
- docs: several accounts per service, in the widgets docs, plugins docs and the manual ([12b78a3](https://github.com/bromigos-org/bromigOS/commit/12b78a338e164a0e9894acbbfc0c45984b8e2c70))
- docs: layouts, keep-clear areas, a layout per theme and Tidy up, in docs/widgets.md, the theme folder, the manual's Panels page and first run; commands regenerated ([ca1407d](https://github.com/bromigos-org/bromigOS/commit/ca1407d01399b5c5b40e62252331e910075b4ef4))
- docs: the den TV on every screen at once (sized streams, sound on one screen, covering, max_playing and its measured cost), shows you pick, and the channel guide (live/README.md, the manual's Themes and worlds, keys, panels and glossary, docs/settings.md, widgets.md, homelab.md, lib/README.md) ([be763c9](https://github.com/bromigos-org/bromigOS/commit/be763c91d498a1e63f669c2e55548615f23e8c14))
- docs: SUPER+ALT+C in the keys page and the SHORTCUTS panel: VECTOR reads Claude's replies aloud as they finish (on/off) ([e1170f5](https://github.com/bromigos-org/bromigOS/commit/e1170f537236a1eafb8b5270f4402eafb66d7d14))
- docs: bring media tasks together and retain shipped release highlights ([32001fc](https://github.com/bromigos-org/bromigOS/commit/32001fc1ddc4ef29ed6a589c60d9e71f177a627b))
- docs: include the merged lab provisioner and media title fonts ([aad6e22](https://github.com/bromigos-org/bromigOS/commit/aad6e2203ce12298f07018d3722731c6efadc008))
- docs: include the themed shell and refresh the command audit ([e0580c1](https://github.com/bromigos-org/bromigOS/commit/e0580c1c9686ddb6b2d6d181f4e9bd404d13747a))
- docs: describe mirrorlist files and keep AUR package releases in sync ([6d6dc92](https://github.com/bromigos-org/bromigOS/commit/6d6dc92128695312310e54efb1f200295159c9aa))
- docs: fix agent notes link in the rendered manual ([5ec75f8](https://github.com/bromigos-org/bromigOS/commit/5ec75f8b38ca43cdf065af133f812556b1556e4a))
- docs: describe agent provisioning in the homelab package README ([9706afd](https://github.com/bromigos-org/bromigOS/commit/9706afd3791453032bdf709b0b59efac5c19713b))
- docs: distinguish den equipment controls from channel pictures ([9b8ee4e](https://github.com/bromigos-org/bromigOS/commit/9b8ee4eef7eea11cda5c7600315d66ba7125b751))
- docs: add a concise pull request template ([48983f1](https://github.com/bromigos-org/bromigOS/commit/48983f12d35e7aacabc069e8be7f099147a380c2))
- docs: Wick · Tidewell and Wick · Mire in theming, the manual, the README and the glossary ([c0767f1](https://github.com/bromigos-org/bromigOS/commit/c0767f1f832d50a256337917c2de065bd32462fb))
- docs: theme-switcher.webp redrawn with all eleven themes, each preview the whole desktop ([10c0bd7](https://github.com/bromigos-org/bromigOS/commit/10c0bd7efcc9142420b53b82141ffa76d54404a0))
- docs: give VECTOR files and pictures (drag them on, paste, + ATTACH, ask --file) ([5265c28](https://github.com/bromigos-org/bromigOS/commit/5265c28725120725db1d2e188aa3bea1e9ae96d5))
- docs: Find my lab, in the homelab pages, first run, Settings and the guided setup ([ac74252](https://github.com/bromigos-org/bromigOS/commit/ac74252901690e2eeb5d8ea0092eab92cf4bbf19))
- docs: the Bromigos account sign-in, in the manual, the lab setup, Settings and the command reference ([759232a](https://github.com/bromigos-org/bromigOS/commit/759232af74c76757a8eee899aed294ddb6c04fef))
- docs: your keyring: oo7, the login that unlocks it, bromigos keyring, and what sign-in says when there's none ([c145e67](https://github.com/bromigos-org/bromigOS/commit/c145e67406051873ef837cb87814e960bc42d3b2))

### Packaging and CI

- packaging: every channel is also copied to a private Cloud Storage mirror, ready to go public with tools/release/go-public.sh ([431fe6a](https://github.com/bromigos-org/bromigOS/commit/431fe6af88bc35abf98af03214e04870813bc560))
- packaging: the public mirror is a Cloudflare R2 bucket, not Cloud Storage (free downloads) ([0e809c3](https://github.com/bromigos-org/bromigOS/commit/0e809c37df119e6520845ebf0c600fe3a6044bf6))
- packaging: the public mirror leaves out 1password; its databases are repo-removed copies, signed again ([5d0747b](https://github.com/bromigos-org/bromigOS/commit/5d0747bcb5d776781c2d4eec4765fd47628da52c))
- packaging: on GitHub's runners the R2 bucket is the primary (PKGS_PRIMARY=public), with a test folder (PKGS_ROOT) ([f340f7d](https://github.com/bromigos-org/bromigOS/commit/f340f7d5dbd6f6dc46fbb0c43d6ab0c28287a34d))
- ci: every workflow can run on GitHub's runner (input hosted), as once the repositories are public ([3be8b2b](https://github.com/bromigos-org/bromigOS/commit/3be8b2b7164e7050635aef551d4070f6ab34b072))
- packaging: the den TV's player and YouTube support (python-mpv, mpv, yt-dlp, deno) and every built-in panel's tools (playerctl, cava, pacman-contrib, github-cli, python-icalendar, python-dateutil, libsecret, git, zoxide, iputils, …) are installed with bromigos-live and bromigos-widgets instead of left optional ([81d55b4](https://github.com/bromigos-org/bromigOS/commit/81d55b429e93ef24272d3ea99b444de1f00df21f))
- packaging: noto-fonts-cjk with bromigos-settings, so Japanese, Chinese and Korean titles (anime openings, music, YouTube) draw instead of empty boxes ([2232ede](https://github.com/bromigos-org/bromigOS/commit/2232ede9d090986256954cd6bf3211a4198d8e00))
- packaging: require mehshell with theme colour support ([9c9a475](https://github.com/bromigos-org/bromigOS/commit/9c9a475795c6ff53843e8943c9fc7e75c855a1c8))
- packaging: bump mehshell for the package conflict declaration ([50a5260](https://github.com/bromigos-org/bromigOS/commit/50a52601e1d0f3d2a6868b4f5ecb4ca1bfe6f304))
- packaging: publish the keyring and mirrorlist through the AUR ([6f8c6e3](https://github.com/bromigos-org/bromigOS/commit/6f8c6e3cc345adbb7f1a402f59db05e58148ee76))
- packaging: pin AUR sources only when bootstrap files change ([6dfbd1f](https://github.com/bromigos-org/bromigOS/commit/6dfbd1f6f00bfc918b6758350369fe4325d4b1d0))
- packaging: use the release credential for immutable source tags ([3025f08](https://github.com/bromigos-org/bromigOS/commit/3025f0863cc548487b8c3736506ae619f0947047))
- packaging: reuse verified source tags without moving them ([e62c4fc](https://github.com/bromigos-org/bromigOS/commit/e62c4fcfa954fd0928679954301ac4b9952aae8c))
- packaging: build herdr with a pinned zig 0.16.0, and move to 0.9.5 ([f166c5d](https://github.com/bromigos-org/bromigOS/commit/f166c5d791132cf2047ffa41615c3dcb5ecd0a71))
- packaging: brodec-desktop, BRODEC's optional desktop app, signed here and published to every channel ([d662dbf](https://github.com/bromigos-org/bromigOS/commit/d662dbf150fc3c5d8e3dbb824d0faa3226159878))
- packaging: oo7, the keyring, built from upstream so a text console login unlocks it ([9dc2253](https://github.com/bromigos-org/bromigOS/commit/9dc2253c487fc957f7c1629444a1614c1b7cf4c6))

### Other

- release-tools: go-public.sh compares with sha256sum, not cmp (archlinux:base has no diffutils), and CI installs jq ([62a638c](https://github.com/bromigos-org/bromigOS/commit/62a638c28a3058b4fdf8e64136980ee7ba3b0052))
- release-tools: go-public.sh checks the prepared branch's address without grep -q in a pipe ([c150b33](https://github.com/bromigos-org/bromigOS/commit/c150b3312bda8115e5434f3c4d84cbf3523e06ea))
- tests: fixtures use the documentation ranges (RFC 5737 IPv4, RFC 7042 MACs), so the privacy guard is quiet ([b33ec71](https://github.com/bromigos-org/bromigOS/commit/b33ec71b736eba1da16b81188c1b0b0a764f1f7a))
- tests: each `privacy: allow` in the release tests says why the private shape is needed ([5984a6c](https://github.com/bromigos-org/bromigOS/commit/5984a6c12cef887dd477733fb7de791982086bce))
- release-tools: go-public.sh --ci moves CI to GitHub's runners (--ci --private moves it back) ([841c3d8](https://github.com/bromigos-org/bromigOS/commit/841c3d817686d96f4399add6ada5ae482341889e))
- release-tools: go-public.sh --repos makes bromigOS, vector and extensions public; a custom domain keeps r2.dev on ([1207fdc](https://github.com/bromigos-org/bromigOS/commit/1207fdc9f0da88fdcdc6591c2c8145eeb8c483a4))
- packages: public at https://pub-725f58eecf5c43748779ba6473eb9720.r2.dev (install.sh's default; the docs drop the early-access notes) ([0ddf657](https://github.com/bromigos-org/bromigOS/commit/0ddf6571605254d90f1ef7db65d25d4c81b5936f))
- packages: the public repository is https://pkgs.bromigos.org ([50dd91d](https://github.com/bromigos-org/bromigOS/commit/50dd91d5f17c13e0a8093fb024ea2ac8506bd073))
- bromigos panels edit|add|gallery, Super+Alt+W, the menu's Edit widgets, and Settings › Widgets as the widget gallery with Get more widgets from the catalog; reset writes bromigOS's layout through a symlinked layout.json instead of removing the link ([ee61649](https://github.com/bromigos-org/bromigOS/commit/ee61649d2910a063a3a13d3300f5cac370116330))
- tests: e2e_widgets_nested.py drives edit mode in a nested Hyprland with a virtual pointer (vptr.py) and keyboard; the Settings shortcuts driver passes render as the dict the app reads ([31e5857](https://github.com/bromigos-org/bromigOS/commit/31e585785320527381ec01f0bc243619056b3927))
- tests: edit mode's resize snaps between size classes, and the pointer arrives before it presses ([51fb75e](https://github.com/bromigos-org/bromigOS/commit/51fb75e2f88fb213a7dadc77cf15771107946311))
- Install from URL in the widget gallery: a git URL or a folder, checked first (bromigos panels inspect: ext info, and each widget's words read from its code without running it), then Install, the approval, given through an answers file Settings writes and keeps; tested end to end in the nested session with the widget settings form ([b979eec](https://github.com/bromigos-org/bromigOS/commit/b979eece27830f7a4e39ed0494fbdd99b90c744b))
- manual: Make your own widget: from bromigos ext new widget to a widget others install by its link, and into the catalog ([af1d0a0](https://github.com/bromigos-org/bromigOS/commit/af1d0a085b90f33f566f6bb65a44dc24c71a440e))
- packages: the checks' own dependencies: bromigos-desktop's tests read the widget gallery and bromigos-widgets' tests draw every panel, so both check with python-cairo, python-gobject, pango and python-psutil ([ab31e6c](https://github.com/bromigos-org/bromigOS/commit/ab31e6ca2cfb19d1fab258dcbc16246b9c8c6de5))
- tests: e2e_widget_plugins_nested.py: in a nested Hyprland, the gallery lists every built-in plugin widget and the homelab's, each is added and draws without an error, the tray finds them by search, and TWITCH's settings form in its sign-in states (widget_form_driver.py, with a stand-in sign-in that reaches no service) ([6608392](https://github.com/bromigos-org/bromigOS/commit/66083925add7dcabc5356401a0dc3f200c8add42))
- bromigos_account: Plex, signed in with its PIN (a code entered at plex.tv/link, no app of your own), and plex_claim_token() for a new Plex server's PLEX_CLAIM ([4558097](https://github.com/bromigos-org/bromigOS/commit/4558097a15d6ee4dbec96f2fdd7c52143ca49f8b))
- widget settings form: the whole title ("Twitch settings"), each text field with its label and hint above its box, the path as ~/…, the device code laid out down the row (the code large with Copy and Open the page, the page's address short), "Waiting for you to approve" once the code shows, the connect help said once; the forms can show in a host's sheet; gallery pictures take demo readings when asked ([9b68593](https://github.com/bromigos-org/bromigOS/commit/9b6859372882ad877235d0ba2130c84f5f86f05c))
- Customize: the theme switcher and the widget gallery in one window, with tabs (Themes | Widgets; Ctrl+Tab). Themes keeps everything the switcher did and adds Make your own (theme new --from), Remove (yours only), Install from URL and the options in Settings; Widgets is the gallery as cards: on/off, sizes, Add to desktop, settings, Remove, Install from URL, Get more, Arrange on the desktop. bromigos customize [--tab]; the launcher's Customize entry; Settings links to it ([694e910](https://github.com/bromigos-org/bromigOS/commit/694e91023d1536638c7e2b25c3b26adb82aee605))
- Customize: the Widgets tab four or five cards to a row with pictures that fill them, its category buttons from what the widgets declare, every gallery picture drawn with made-up readings (SHORTCUTS and FIELD NOTES too, never empty on a fresh install); the Themes tab marks an older preview quietly (DRAWING only when there's none), and a held render shows the finished state ([5789d0d](https://github.com/bromigos-org/bromigOS/commit/5789d0d5b28fcce93bbba4f6b196ac7c1f09aff6))
- lib: bromigos_tv, the den TV's channels and their wall-clock schedule (in order, or shuffled the same all day; each screen's channel, sound and volume remembered), and bromigos_youtube, a playlist or channel through yt-dlp --flat-playlist -J, cached, live now, and keeping videos in the Plex and Jellyfin layout at a low priority, never on battery, under a size cap ([9fc4674](https://github.com/bromigos-org/bromigOS/commit/9fc4674b5ecf24b59523b8b6d02200f81e1b770e))
- lib: bromigos_youtube.channel_videos() for the YOUTUBE panel, and live_now() says False when a channel isn't live (None only when it can't tell) ([ee440c2](https://github.com/bromigos-org/bromigOS/commit/ee440c2276dd26932e7d4d4f28a98c4eaae363a0))
- Customize › Widgets: each row of cards as tall as its own cards, so a short last row stays short; the flow boxes aren't homogeneous any more, and each card is a column wide, keeping the grid at four or five to a row ([9f328e7](https://github.com/bromigos-org/bromigOS/commit/9f328e7fae7ea580cca4258072d4d6c272e892cb))
- accounts: bromigOS's own Twitch app ships as the default, so the TWITCH panel goes straight to Sign in with nothing to register; your own client ID still wins (bromigos account configure) ([9070721](https://github.com/bromigos-org/bromigOS/commit/90707218e395bbe18abca3d3698fff61c356cf75))
- accounts: bromigOS's own GitHub OAuth app (device flow) ships as the default, used when gh isn't signed in; your own client ID still wins ([cecd9b9](https://github.com/bromigos-org/bromigOS/commit/cecd9b999ec80a81d6074fd52b108f468e8230a0))
- accounts: bromigOS's own gitlab.com application ships as the default (device grant, no secret); a self-hosted GitLab still asks for an application of its own ([721d73d](https://github.com/bromigos-org/bromigOS/commit/721d73d3630773b9702ab34592166b240a59a914))
- accounts: several named accounts per service (gitlab.com and your company's GitLab side by side) ([b25ba16](https://github.com/bromigos-org/bromigOS/commit/b25ba164e909ae9197944a6448e6ba26e0e5a8f5))
- den TV: mpv trusts the system's roots plus the lab's CA (one bundle), not the lab's CA alone, which failed every YouTube stream ("Peer certificate failed verification": static on the den, a black full screen that closed) ([51f6adc](https://github.com/bromigos-org/bromigOS/commit/51f6adc0c0ec913d6c04469dbeb05cc7bdb76d1b))
- customize: a Layouts row at the top of the Widgets tab (a miniature of the screen per layout over the scene, the theme's own first, Made for <theme>; Use this layout, Undo, Tidy up); Settings › Widgets: Layouts and Tidy up, and overlapping widgets named; previews: a scene's plugin widgets shown, the made-up lab for any homelab widget; tools/widgets/render-layouts.py; the nested e2e applies a layout, undoes it and tidies ([3747fc6](https://github.com/bromigos-org/bromigOS/commit/3747fc6d662f2ad7a339d836848b586b96c6aad8))
- den TV: every screen plays its own channel at once (a player each, sized streams, sound on one screen at a time), channels of picked shows that shuffle or take turns, YouTube resolved ahead, and a config writer that keeps comments ([05cd7c3](https://github.com/bromigos-org/bromigOS/commit/05cd7c32abfe847b231510f6cdc7bcd8f5aefb56))
- den TV: the guide's card menu is a popover of buttons (Settings exports no actions: the VECTOR guard), and the TV tests clean their sandboxes (test_tv's kept videos left 764 MB in /tmp per run) ([9d34cdc](https://github.com/bromigos-org/bromigOS/commit/9d34cdc467269898fb7936124b79ff1bdbcd4b8a))
- den TV: every channel on every screen unless its `screens` says otherwise, [tv.start] for each screen's first channel, one player for two screens on the same channel (the same moment), and `bumpers = true`: a station card opening each item ([677650c](https://github.com/bromigos-org/bromigOS/commit/677650cb8cf456e19086f2ad5e5332e4fd01c553))
- den TV: the channel guide shows each channel once with a tune button per screen (lit where it's on air), bumpers and screens in its menu; the MEDIA panel is a remote for the three screens (choose one, then channel, sound, full screen, guide); docs ([a613e2c](https://github.com/bromigos-org/bromigOS/commit/a613e2cf1bba3e215e545a761dcaecba143a0964))
- den TV: no more transcode floods. A screen sharing another's channel never opens a stream of its own (it reloaded every frame); the drift check seeks at most every 10 s (it seeked every frame for a second); files the GPU decodes cheaply play direct; a screen's transcode is ended when it moves on, each screen with its own device id ([449def3](https://github.com/bromigos-org/bromigOS/commit/449def3bab5c7204e2abd4dd009b7b3248ea1db0))
- tests: give the live wallpaper ownership test a distinct module name ([e28a9fd](https://github.com/bromigos-org/bromigOS/commit/e28a9fdcad640fdc2e082b1dba197457d4cb2c2b))
- test: fix lab snapshots to a known palette and colour mode ([e3d5f36](https://github.com/bromigos-org/bromigOS/commit/e3d5f36af3994c78c24426c563cb09e9a2397213))
- shell: add themed mehshell and a saved prompt choice ([cbe7f31](https://github.com/bromigos-org/bromigOS/commit/cbe7f3189ab2b2aa659755b6953b141ab2430244))
- fix(media): quit safely and navigate between tabs and content ([a0b1fd1](https://github.com/bromigos-org/bromigOS/commit/a0b1fd117ff5e7dd9cd9dd190144828cba2b1947))
- media: share den TV channels across the media library, guide and CLI ([b982967](https://github.com/bromigos-org/bromigOS/commit/b982967240b59127df39ce36df8ceea9c078df79))
- tv: refresh channel state and stop playback for emptied picks ([86ffb4e](https://github.com/bromigos-org/bromigOS/commit/86ffb4e34cb18d8b5b8da8716609126758c40cc9))
- media: let h and l move across the top tabs ([545cff7](https://github.com/bromigos-org/bromigOS/commit/545cff7753dd1d0d27d97dc57b24335661d054b1))
- media: confirm deletion with Delete and Cancel buttons ([07cbaa8](https://github.com/bromigos-org/bromigOS/commit/07cbaa834cff9d9269bccdb73492615ce29740ac))
- Add hold-to-dictate with a live transcript at the cursor ([e68047b](https://github.com/bromigos-org/bromigOS/commit/e68047bff958a17dfb86f44d1f11349b60405b11))
- Install the dictation keymap library for package checks ([404ecb3](https://github.com/bromigos-org/bromigOS/commit/404ecb3914378b0129fbb221899ae56bed624202))
- Make the dictation idle test independent of runner uptime ([acf7e2d](https://github.com/bromigos-org/bromigOS/commit/acf7e2ddb27e2e194a74a1620434da0286e574a9))
- Give Media a Search tab and keyboard-operated delete confirmation ([9d268ce](https://github.com/bromigos-org/bromigOS/commit/9d268cea4a1d97459269f81299fd93d7fe135199))
- Make adding Media titles to channels visible in every title tab ([942609c](https://github.com/bromigos-org/bromigOS/commit/942609ccc67c6eedb9e512acd8cbbfcd679823eb))
- Show channel memberships on Media selections and hover hints ([c008cd4](https://github.com/bromigos-org/bromigOS/commit/c008cd4187751b924820e3d8e20ff7f12a866216))
- Report real media transfer totals and stalled torrent states ([1f1b6d3](https://github.com/bromigos-org/bromigOS/commit/1f1b6d3eae8a44c952ac6e52b6868a3cf7190cd7))
- Keep skipped channel progress when retuning the den TVs ([5ff576b](https://github.com/bromigos-org/bromigOS/commit/5ff576bb0b35a78db04344e7e0f8654ad143353e))
- Make Media and Lab navigation and confirmations consistent ([bb4aa80](https://github.com/bromigos-org/bromigOS/commit/bb4aa800fff6c390414126bc3db5510094f58a8f))
- Preserve the lab form cancel button explanations ([fd281fd](https://github.com/bromigos-org/bromigOS/commit/fd281fdff9d5b93b10cb49f096f921570ac9e682))
- tests: check tray embedding before opening its menu ([6057f5d](https://github.com/bromigos-org/bromigOS/commit/6057f5d76408dac818671c96ec334ebe73f3b516))
- game: confirm exit visibly and document first-login activation ([3d1ad27](https://github.com/bromigos-org/bromigOS/commit/3d1ad278312883ea8e5ab03850a022c9e088ab37))
- storage: add local drive planning and verified data migrations ([2aaa1d4](https://github.com/bromigos-org/bromigOS/commit/2aaa1d44489ca2310f95ed494fb74f1459d41b60))
- storage: group capacity and add reviewed snapshot cleanup ([d7e3bf2](https://github.com/bromigos-org/bromigOS/commit/d7e3bf2ff23f9391512e1884a407f9f43a9670ec))
- storage: execute planned native cache cleanup ([5d90011](https://github.com/bromigos-org/bromigOS/commit/5d900117c0b3b8953782d19581c858b46a4ee415))
- storage: draw smooth usage bars in desktop terminals ([22d963f](https://github.com/bromigos-org/bromigOS/commit/22d963f81a94e93750486a1e0c81e8434bf060d4))
- console: add font presets and ship TTY-aware mehshell ([c9cdd1e](https://github.com/bromigos-org/bromigOS/commit/c9cdd1e2c09038c7a8a19e85d5c0c3dc504a7d3b))
- console: brand login and add keyboard power and splash controls ([725ba33](https://github.com/bromigos-org/bromigOS/commit/725ba337f830d15191c2cae52510c8ce66d08ce3))
- feat: add bromigOS shell diagnostics and prompt controls ([1255dbd](https://github.com/bromigos-org/bromigOS/commit/1255dbd99c7715af44c914761db4b2adb3b9a8c9))
- feat: save and manage widget layouts from Customize ([ff71899](https://github.com/bromigos-org/bromigOS/commit/ff7189977157c87c591d082b1190d1b1fa46cbc6))
- fix: hide monitoring helpers from lab alerts ([d9041ef](https://github.com/bromigos-org/bromigOS/commit/d9041ef05f326a69dcd955de6adf6bb1d105db91))
- fix: discard late lab dashboard reads during shutdown ([dccb1ee](https://github.com/bromigos-org/bromigOS/commit/dccb1eedc27428986b3ea146b0f7bfc044019048))
- hardware: prefer the GPU with connected monitors at login ([d92e3ae](https://github.com/bromigos-org/bromigOS/commit/d92e3aed2aaadde7fa8b67ae073e7019664ed37f))
- shell: ship the mehshell command status fix ([3f39360](https://github.com/bromigos-org/bromigOS/commit/3f393602e0684bb9b4d1cf79a7532bc16b9920ad))
- fix(shell): recover desktop access in persistent terminal panes ([c52f271](https://github.com/bromigos-org/bromigOS/commit/c52f271e6602594af8f45632c87b8be25d59be4c))
- fix(live): smooth the rotating emblem rim across GPUs ([a9aa27d](https://github.com/bromigos-org/bromigOS/commit/a9aa27d37093396cc503dbbc4ac91997b5135567))
- defaults: a Markdown notes kind, offering Zettlr ([91042cb](https://github.com/bromigos-org/bromigOS/commit/91042cb325f19bb96b1dcd00cdadfdff3bdca52a))
- previews: NAME-STAMP only, so wick's pictures never take wick-mire's or wick-tidewell's ([933ff3e](https://github.com/bromigos-org/bromigOS/commit/933ff3e7a39a31fbab8922c9d180826d89c6bbe6))
- previews: the whole desktop again on kwin 6.8, and a wrong-size picture is never kept ([1e3ffdf](https://github.com/bromigos-org/bromigOS/commit/1e3ffdf84b05074ff3ecc577633e7a5b508bf564))
- tests: the nested harness at the size it asks for on kwin 6.8, and it stops if not ([edba131](https://github.com/bromigos-org/bromigOS/commit/edba131082e412f84c2486764109deb766ceaab4))
- previews: the nested Hyprland never takes a login session, so it draws and grim gets its picture ([529f193](https://github.com/bromigos-org/bromigOS/commit/529f193c3207493def382676c68381fbfb717623))
- manual: VECTOR's attach button is a paperclip ([9fde699](https://github.com/bromigos-org/bromigOS/commit/9fde6992b34302a92da9926493e7861ff1e4b297))
- account: Bromigos is a sign-in provider, with OIDC discovery, rotating refresh under a lock and BROMIGOS_TOKEN ([174460c](https://github.com/bromigos-org/bromigOS/commit/174460ce7d9292bc96f2e61a8f26dea708fab8b3))
- account: bromigos login, logout and whoami: a code on the website, an SSH key, or a personal access token ([5023094](https://github.com/bromigos-org/bromigOS/commit/50230947bccd92c0118246a224eaf27bd7643034))
- keyring: bromigos keyring status and setup; your login unlocks the keyring, and an update sets it up once ([df30e1b](https://github.com/bromigos-org/bromigOS/commit/df30e1bf17305b4dacb66396cde8e3627cb89265))
- login: check the keyring before the code is shown, and say keyring errors in plain words ([333d043](https://github.com/bromigos-org/bromigOS/commit/333d043dac8fc1c7bf54a5aa8a18fcf25f96d04c))

### VECTOR (bromigos-vector)

#### Changed

- Pr_merge never merges a homelab PR until its `validate` check has passed (REQUIRED_CHECKS); a missing check is waited for, not the 150 s "no CI" grace, since Argo CD deploys whatever lands on master ([285835c](https://github.com/bromigos-org/vector/commit/285835cc3f929b4ec51a2a232c87624ac56c936a))
- VECTOR's dotfiles clone uses his public_repo token; the org's repos his fine-grained one (bromigodev's all-scope token is out of his sandbox) ([b79de0b](https://github.com/bromigos-org/vector/commit/b79de0b3d82444201aea9e71b9ea1821dbe339b2))

#### VECTOR

- holo: the transcript ends above the input box, however tall it grows, instead of at a fixed 78 px that the box covered ([247ba80](https://github.com/bromigos-org/vector/commit/247ba8099a67a18957696e9a30ac00169b3bf741))

#### Docs

- docs: CONTRIBUTING.md (build, test, commit style, how his safety rules affect a change) and CODE_OF_CONDUCT.md (Contributor Covenant 2.1, contact@bromigos.org), linked from the README ([e5f819e](https://github.com/bromigos-org/vector/commit/e5f819ec3c401867d90715d199d62290a0597ee8))
- docs: the secrets command is `bromigos secrets sync` ([934776c](https://github.com/bromigos-org/vector/commit/934776c8a029952bea43247417466a582a30a21f))

#### Packaging and CI

- packaging: copy each channel to the private Cloud Storage mirror too, like bromigOS's publish.sh ([141b492](https://github.com/bromigos-org/vector/commit/141b492a9125527d6cc113d5ca745b56ecb7c96b))
- packaging: the public mirror is a Cloudflare R2 bucket (PKGS_PUBLIC_*), like bromigOS's publish.sh ([fc71354](https://github.com/bromigos-org/vector/commit/fc71354fc72253cd0b83836ec00241cd1e1e7fcc))
- packaging: the public mirror leaves out 1password, as bromigOS's publish.sh does ([b284266](https://github.com/bromigos-org/vector/commit/b284266b4e8e74dceac9aebc08519110d9aa1851))
- packaging: on GitHub's runners the R2 bucket is the primary (PKGS_PRIMARY=public), as in bromigOS ([dbe7a10](https://github.com/bromigos-org/vector/commit/dbe7a105f030eab94af4c50bf4cb8cd6c66b97e4))

#### Other

- privacy guard: the RFC 7042 documentation MACs (00:00:5E:00:53:xx) pass; test-devflow's LAN address is marked as needed ([cbbe4d2](https://github.com/bromigos-org/vector/commit/cbbe4d29f20f4896941d0c2e53acb0f91eef794c))
- tests: each `privacy: allow` in test-privacy-guard says why the private shape is needed ([6f9f1f2](https://github.com/bromigos-org/vector/commit/6f9f1f289789e70aefac64f5d4e9d573dda57554))
- media: media_search, media_get, media_status, media_upcoming, media_recent, media_language: VECTOR asks the homelab's media stack for films, shows, anime and music (bromigOS's `bromigos lab media`) ([2dfe753](https://github.com/bromigos-org/vector/commit/2dfe7536b279a54a08686c5bb532eeeb917278e2))
- tests: test-media.py brings an empty private-overlay module where bromigos-core isn't installed (CI), as test-devflow.py does ([db85c54](https://github.com/bromigos-org/vector/commit/db85c547173fedfccba8e87a5f8422069a29a816))
- media: media_delete: a title, a season, episode files or an album, files and all, only when Sir's latest words name it and ask for a delete ([b2a0448](https://github.com/bromigos-org/vector/commit/b2a0448acf4d9387173c5fa67e7f0e4fc04a96d3))
- claude: claude_sessions, claude_read, claude_search, claude_memory, claude_logs, claude_say_latest, claude_follow: VECTOR reads Claude Code's transcripts, jobs, memory and logs directly, read only and redacted ([cda25bb](https://github.com/bromigos-org/vector/commit/cda25bbb6b37ca034053e51397152ac754e7281d))
- tv: audited channel tools for the desktop and phone picks ([f530c8c](https://github.com/bromigos-org/vector/commit/f530c8c16a3535eb5716b43f7d04c53efaa52670))
- tv: resolve legacy channel names consistently ([a32f62e](https://github.com/bromigos-org/vector/commit/a32f62eabf2b731540d6c312e887d19938ec771c))
- tools: play specific media and use the den TV remote ([c126ff9](https://github.com/bromigos-org/vector/commit/c126ff9137f5c88cc3564f61ba5fd138a5a79bf7))
- attach: files and images for VECTOR: drop them on him, paste with Ctrl+V, + ATTACH or ask --file; chips by the box, read as data never instructions, never a secret, only references kept ([dd34c38](https://github.com/bromigos-org/vector/commit/dd34c3878ced0cd88c976c29560703952dce835a))
- attach: the attach button is a paperclip drawn in the button's theme colour, not "+ ATTACH" ([69a188c](https://github.com/bromigos-org/vector/commit/69a188cda4f5fb1251df80874b76150656b04edf))
- attach: the paperclip is the input box's right end, the box's height and joined to it, with a larger icon centred in it ([eaea66e](https://github.com/bromigos-org/vector/commit/eaea66e4de41f4104cdcde926e94e1ddcf13afdc))
- portrait: VECTOR's portrait as a stream of frames (holo/portrait.py), so another app shows him live without running his renderer inside it ([1b98754](https://github.com/bromigos-org/vector/commit/1b98754c259b229534be471e6bdd84ff778217c4))

## [0.1.2] - 2026-10-09
<!-- release: 0.1.2-rc2 -->

Release candidate v0.1.2-rc2.

Since v0.1.1. In plain words: the manual's What's new (manual/src/whats-new.md).

### Added

- VECTOR's emergency switch on the desktop: SUPER+CTRL+ESCAPE, a power mark on the bar (a red VECTOR OFF while he's off), and one switch in Settings › VECTOR; bromigos status reads it ([d7b3296](https://github.com/bromigos-org/bromigOS-archive/commit/d7b329696eb06217b24db045b6167dcfec04f47d))

### Core (the bromigos command)

- core: bromigos peripheral: optional peripheral modules, and setup's peripherals section ([0aef1cf](https://github.com/bromigos-org/bromigOS-archive/commit/0aef1cf6f445c322bac2d93741a541793d06f3e1))
- core: bromigos hw: the GPUs and the machine's kind from files, drivers from NVIDIA's and Mesa's own tables, hw setup ([bca146e](https://github.com/bromigos-org/bromigOS-archive/commit/bca146e4a6b26bf5f9242b0010a9a31eb1e76f90))
- core: accessibility: reduced motion and high contrast, set from bromigos accessibility and setup ([2f5ab91](https://github.com/bromigos-org/bromigOS-archive/commit/2f5ab91059297f3fd94a5b82d0fd741d2f6e5f05))
- core: idle and lock as data: idle.toml, `bromigos idle`, hypridle rendered and restarted ([8efee8e](https://github.com/bromigos-org/bromigOS-archive/commit/8efee8ec508e3f151f3756ec66ea322cc890d128))
- core: bromigos idle waits for the compositor to start the new hypridle (2 s at most) ([7241f66](https://github.com/bromigos-org/bromigOS-archive/commit/7241f66cd198fe92a2337bb75b70729ca7bafc51))
- core: bromigos idle start --detach: hypridle started in this session now, unless it runs ([8252b04](https://github.com/bromigos-org/bromigOS-archive/commit/8252b04645bd602398bb08a2e64d0b0338f6ae45))
- core: idle: a file written in the second before hypridle started isn't newer than it ([366645a](https://github.com/bromigos-org/bromigOS-archive/commit/366645a7d78e72b450a4f584e835bf1c7be60554))
- core: the theme switcher's previews drawn in the background after update, ext install/update and theme new ([3037244](https://github.com/bromigos-org/bromigOS-archive/commit/3037244cb5a70cc2b9c0a209ae249aa21597f09d))
- core: pacman's hooks hold Hyprland's auto-reload while a transaction replaces its config, then one verified reload ([d9d2763](https://github.com/bromigos-org/bromigOS-archive/commit/d9d2763b0513594b0dfb1854f50ff082e27e429a))
- core: bromigos peripheral follow ID vector|theme: what a module's lighting follows ([3d94809](https://github.com/bromigos-org/bromigOS-archive/commit/3d94809670ed86e334f32e01514ddd3638355d33))
- core, desktop, live, widgets, homelab: every bromigOS window in the app launcher, listed once in the menu ([35d2c6f](https://github.com/bromigos-org/bromigOS-archive/commit/35d2c6fe060a803495eaaa7e6e5cdc2e3447da79))
- target: check and probe say when a better model would fit the lab's GPUs (the lab model catalog) ([d109c2a](https://github.com/bromigos-org/bromigOS-archive/commit/d109c2a9cd4ace8ca0a3c3dfde284eab6a2f0266))
- core: rollback status says bromigos update makes its own snapshot pair (snap-pac's brackets any other pacman run) ([25f5e4b](https://github.com/bromigos-org/bromigOS-archive/commit/25f5e4bf8aea63383fb81ad4c62f57f218f92593))
- core: setup's module comment says where the monitors go (a bromigos.monitors block in the user's hyprland.lua, the primary in monitors.toml), not a monitors.lua, and lists the extensions section ([0884b52](https://github.com/bromigos-org/bromigOS-archive/commit/0884b523579e8dff6d020d16cea030028f92fc3d))
- core: bromigos whats-new, and the first update after a new release says so ([4e9d20c](https://github.com/bromigos-org/bromigOS-archive/commit/4e9d20c9ee5619aca4901a8fd52fc2842c8232ca))
- core: the AUR: paru at install and through a migration, AUR packages inside bromigos update's snapshot pair, bromigos aur, AUR-only NVIDIA drivers offered by hw setup ([9be878f](https://github.com/bromigos-org/bromigOS-archive/commit/9be878f5937be111f1d366fa5c4e36f39083cf6a))
- core: setup's Homelab page starts on Skip, so Enter goes on; the homelab.toml choice wants a path first ([ea7ccf4](https://github.com/bromigos-org/bromigOS-archive/commit/ea7ccf43af1272862515d9a1f3e4dc32a015f28f))
- install.sh: piped into bash, it asks on the terminal; with no terminal it needs --yes ([676456b](https://github.com/bromigos-org/bromigOS-archive/commit/676456bfd22e2b3e0677d09c291b05fd8e903ca3))
- core: the private overlay is decrypted at login, and again when it changes, as the docs said ([749e38d](https://github.com/bromigos-org/bromigOS-archive/commit/749e38d880d79fac4bb6ee299c4c9e6ee5645f67))
- core: bromigos update --rollback in a snapshot booted from the boot menu makes that snapshot the root ([17247b7](https://github.com/bromigos-org/bromigOS-archive/commit/17247b76c7961f995e6bd83e39dbd7cf2acfb832))
- core: an update from 0.1.1 renders the theme again: the templates default a11y, and an update that replaced bromigos hands the theme to the new one ([0a0791c](https://github.com/bromigos-org/bromigOS-archive/commit/0a0791cc7d15e1ac7288f122dbe8e185456f55aa))
- core: bromigos update holds back the live layer and VECTOR while a new NVIDIA driver or kernel waits for a restart, and ends by asking for one ([b62b79f](https://github.com/bromigos-org/bromigOS-archive/commit/b62b79ff0144b41d9e5948fd1b751c045d896595))

### Desktop

- desktop: peripheral modules: the Hyprland loader, the dial and lighting daemon ([d47c01b](https://github.com/bromigos-org/bromigOS-archive/commit/d47c01b62b2c1c094d255119911853d0974d01bb))
- desktop: laptops: the battery and power profile in the bar, profiles in the menu, tap to click and a workspace swipe ([5bafdf5](https://github.com/bromigos-org/bromigOS-archive/commit/5bafdf5c6babbb8cf1a64b12f9d63614a195de34))
- desktop: accessibility: window animations and borders follow it, the menu's rows, the panels ([aa7368e](https://github.com/bromigos-org/bromigOS-archive/commit/aa7368e6c04d14836c85c04fccd05ea9fde6df21))
- desktop: Settings (bromigos settings, SUPER+,): a page registry, Idle & lock complete ([946cbf9](https://github.com/bromigos-org/bromigOS-archive/commit/946cbf90cdd996b4e21ff6f2e039ceeef54f16cb))
- desktop: the bar's idle eye (stay awake's cup) and the Settings gear ([3db8aae](https://github.com/bromigos-org/bromigOS-archive/commit/3db8aae492cabf8ba0c41367e9ee0b24a1d492de))
- desktop: Settings: the accessibility page reads `bromigos accessibility`; the interaction check ([253a72f](https://github.com/bromigos-org/bromigOS-archive/commit/253a72fcc87043b4e0305e04a80a1a89b3f32884))
- desktop: one safe save for every hyprland.lua change, auto-reload off first ([e112bd4](https://github.com/bromigos-org/bromigOS-archive/commit/e112bd495ae2702a844d67f6ff1cb5af63d87057))
- desktop: bromigos keys, the shortcut picker: press the keys to rebind ([fab4711](https://github.com/bromigos-org/bromigOS-archive/commit/fab47112a2af962d51a48bde0fd107d4756e891c))
- desktop: Settings: Shortcuts opens the key picker (bromigos keys) and counts your own ([ca7b9c3](https://github.com/bromigos-org/bromigOS-archive/commit/ca7b9c3aac38f484a8f51deeb2ee39ac2833e4ff))
- desktop: SETUP › Config files: idle.toml, and an edited idle file is applied ([ae5ac6f](https://github.com/bromigos-org/bromigOS-archive/commit/ae5ac6f326e8a56bd8dec9b58b982df6b819511f))
- desktop: Settings: Idle & lock offers to start hypridle when it isn't running ([025dc5b](https://github.com/bromigos-org/bromigOS-archive/commit/025dc5bc844365690e51970a181abefbfbc7d69b))
- desktop: bromigos keys: undo, list --all, --json outcomes; the capture window opaque ([22f17d2](https://github.com/bromigos-org/bromigOS-archive/commit/22f17d2a5e199f9d8e01826fe3daa8e526c2f546))
- desktop: Settings: the Shortcuts page, complete: every key with Change…, yours, reset ([50379e4](https://github.com/bromigos-org/bromigOS-archive/commit/50379e44f5309cd795f647d0bab663e1e42b8ce2))
- desktop: bromigos keys and peripheral modules: K.exclude's keys spelled as the module does ([cba39c1](https://github.com/bromigos-org/bromigOS-archive/commit/cba39c181ecb2652ca558d34e06e35077d600fe0))
- desktop: Settings: Accessibility, complete: motion, a high-contrast switch, the theme measured ([37e6773](https://github.com/bromigos-org/bromigOS-archive/commit/37e6773e8923032e38b5fa26d7ec8f2659fca7f5))
- desktop: a safe save writes through a symlink: a hyprland.lua kept in dotfiles stays linked ([61e8307](https://github.com/bromigos-org/bromigOS-archive/commit/61e8307a470acf6308fd80cfc836aa1af4ff2d58))
- desktop: Settings: a page's icon may name several, the first the icon theme has ([8b9225c](https://github.com/bromigos-org/bromigOS-archive/commit/8b9225c349529ccade6ddd86187b129693f3ccd7))
- peripherals: the lighting can follow the theme (rgb_follow = "theme"): its primary, changing with the theme ([d3a5e56](https://github.com/bromigos-org/bromigOS-archive/commit/d3a5e5695a1e4b42043190215a014654be5b786e))
- desktop: the theme switcher shows each theme as the desktop wearing it, sized to the monitor ([5b82e7e](https://github.com/bromigos-org/bromigOS-archive/commit/5b82e7e03998a9eeadfab8d976316eccc95d7561))
- desktop: the switcher's tests build without Pillow; the Wick's card says DEN ([f873ac1](https://github.com/bromigos-org/bromigOS-archive/commit/f873ac1f08b32e84acf36e6c1132f9fdfc897ab9))
- desktop: bromigos-wallpaper restarts only its own session's swaybg ([9da347e](https://github.com/bromigos-org/bromigOS-archive/commit/9da347e4ca485af2ce4414b7b681371ba9cc9301))
- desktop: theme previews are screenshots of the real desktop: Hyprland nested in a headless kwin ([ad5bf1e](https://github.com/bromigos-org/bromigOS-archive/commit/ad5bf1e897ac3d602aa66cae8a883d48cc8549d3))
- desktop: Settings › Theme: wear a theme from its preview, what moves in its world, the options around it, more themes ([69a57d1](https://github.com/bromigos-org/bromigOS-archive/commit/69a57d17d37b89240c459af6d78d4576f0857f61))
- desktop: Settings: groups, a search across every setting, one page layout, Advanced lines, Sound ([42db24c](https://github.com/bromigos-org/bromigOS-archive/commit/42db24c8044f8a9a041906e676f30e7553e7b2ba))
- desktop: theme previews: the nested Hyprland writes no log (its runtime directory is in /tmp, often small) ([e8070a4](https://github.com/bromigos-org/bromigOS-archive/commit/e8070a489e3e4c7865ec38a6eb68e9e485a8b007))
- desktop: Settings › Theme in the new Settings shell: its header, the search's entries, keyed rows, Advanced lines ([9d92d97](https://github.com/bromigos-org/bromigOS-archive/commit/9d92d973ee91e609aa126bb9f32563092f4173b9))
- desktop: Settings › Lab in the new shell: the lab group, its explanation, the manual's page, and the search's entries (status, models, jobs, doctor, targets, connect) ([64dcd26](https://github.com/bromigos-org/bromigOS-archive/commit/64dcd26dc41590ec82c245feda25f33e5b07a8c2))
- desktop: Settings: Idle & lock, Shortcuts and Accessibility in the new layout: their settings searchable, Advanced lines, Reset to defaults ([f02cc01](https://github.com/bromigos-org/bromigOS-archive/commit/f02cc01d0634fb41c74d0dbe39bfd933795201f3))
- desktop: Settings: the keyboard, end to end: typing anywhere searches, Enter opens a result on its row, Esc, Ctrl+F, Ctrl+1…6, Ctrl+PgUp/PgDn ([e44b322](https://github.com/bromigos-org/bromigOS-archive/commit/e44b3225d5bedc920292baa75eb9df1fa435ef64))
- desktop: Settings › Displays, Network and Bluetooth (bromigos display, net, bluetooth) ([fd3178c](https://github.com/bromigos-org/bromigOS-archive/commit/fd3178c193ca42939aafc8532a820bb9963f1443))
- desktop: Settings › Power, Keyboard & input, Date & time, Notifications (bromigos power, clock, notifications; setup input) ([44fe33d](https://github.com/bromigos-org/bromigOS-archive/commit/44fe33d0a2cf4724297555f1b04e532f5a26f363))
- desktop: Settings › VECTOR, Creation targets, Account, About, Updates & recovery (bromigos memory, about, avatar) ([c76b084](https://github.com/bromigos-org/bromigOS-archive/commit/c76b084ad9487f08404bd94573e331d492297013))
- desktop: Settings › Default apps, Startup, Widgets, Live layer & holograms, Peripherals, Extensions (bromigos defaults, startup, panels) ([b970a8e](https://github.com/bromigos-org/bromigOS-archive/commit/b970a8ef3b8cd72722c8617b753bf07ab6ad745c))
- desktop: Settings: combo rows show their escaped text, group descriptions escaped, Advanced lines plain; renders as a laptop; the Displays end-to-end steps ([611c77c](https://github.com/bromigos-org/bromigOS-archive/commit/611c77c586056d5be24a9051ad06985e177e6c5f))
- desktop: the extensions window and Settings › Extensions share one list (bromigos_extlist); Settings' terminals are bromigos terminal ([dab836d](https://github.com/bromigos-org/bromigOS-archive/commit/dab836d590780764e8c5eedefb168ed27cf8b72f))
- desktop: Settings end to end in a nested Hyprland, 37/37: Displays applied, left to revert by itself, kept, reset; Keyboard & input live; a combo row no longer locks up ([2cd74b3](https://github.com/bromigos-org/bromigOS-archive/commit/2cd74b3fa4c1897fbb73e526719fc31827f8c24d))
- desktop: Settings › Lab without bromigos-homelab: a row for each thing the search finds (greyed, saying why), Connect your lab, where AI runs ([f48bc0b](https://github.com/bromigos-org/bromigOS-archive/commit/f48bc0ba6b24b495bd03fbe7c1407c3e53514197))
- desktop: Settings › Lab › Models: each capability's switch says what it does for that capability (the plan's switch, Always on); the audit with the recorded lab: 0 unhinted (13 before) ([8b9936b](https://github.com/bromigos-org/bromigOS-archive/commit/8b9936b73094ed61d6e269990b6d14ee7fa372e9))
- desktop: Settings › Theme's grid reflows: three cards to a line, two, then one, so it fits a narrow window ([0221fe8](https://github.com/bromigos-org/bromigOS-archive/commit/0221fe84e538bb578b2378e5317276ef8ab4f00b))
- desktop: the theme switcher's previews show the den in a colour theme's colours, and a new live layer redraws them ([38ce275](https://github.com/bromigos-org/bromigOS-archive/commit/38ce27518e6f705e415a45ee1501cf451bb7810f))
- desktop: a colour theme's card says the den behind it takes the theme's colours (since 75a1285), not that it keeps the Wick's green ([95ae68e](https://github.com/bromigos-org/bromigOS-archive/commit/95ae68e187f5e734dcdcac21aac79aedb29dac53))
- settings/sddm: theme.conf says bromigos-settings' PKGBUILD puts the Wick's pictures in assets/, not a build.py that doesn't exist ([a663022](https://github.com/bromigos-org/bromigOS-archive/commit/a663022c6b0a51d9bb743f58f1f89c7855cd47be))
- desktop: the rofi menus' titles read whole again: one quoted string per line in the title theme (rofi read the title as BROMIGOS"; … font: "Geist Mono Bold 12) ([e1ea131](https://github.com/bromigos-org/bromigOS-archive/commit/e1ea13177be058a438e8bdd0460e27f6a779e988))
- desktop, widgets: theme previews draw any panels where you put them and the terminal you want (--panels, --scene), every reading a demo one: the bar's built-in modules showed this machine's (a fixed demo text now, thresholds out of reach), a made-up player fills its middle, WEATHER, WORKBENCH, CONNECTIONS and LAB (a made-up lab, widgets/demo_lab.py, which the decks see too) have demo data; bromigos menu --filter TEXT ([dd4c4c6](https://github.com/bromigos-org/bromigOS-archive/commit/dd4c4c636ff005c3c81548fba4640528a2caad16))
- desktop: the rofi menus' titles sit above the search box again: the title expands (rofi's default for a textbox); a fixed-height one made rofi 1.7.9 and 2.0.0 skip the header's layout and draw the title under the input, in the menu, keys, extensions, the setup tools, the power menu and the quick note; the menu's picture rendered again ([4a1e203](https://github.com/bromigos-org/bromigOS-archive/commit/4a1e20327e795f909594d5f63f368885813f3d39))
- desktop: Alt+Esc suspends with plain systemctl suspend, which logind allows the active session; sudo failed without a passwordless rule ([58b32b5](https://github.com/bromigos-org/bromigOS-archive/commit/58b32b50f8a19545161877cc57b7673d32fbed56))
- desktop: searching Settings for "dark" finds Themes, not Bluetooth's Look for devices ([558159e](https://github.com/bromigos-org/bromigOS-archive/commit/558159ea522487f31731782c9bbd79c00b04cb88))
- desktop: with mod = "SUPER", no key does two things: bromigOS's own Super key a window key would share moves to Alt ([525a107](https://github.com/bromigos-org/bromigOS-archive/commit/525a10761453e1ec3c9e155062f57ffe0bdbbc61))
- desktop, packaging: Settings' F1 and About open the manual installed here, else <base>/bromigos/manual/, where it's published ([64a3bf2](https://github.com/bromigos-org/bromigOS-archive/commit/64a3bf2ef16ea705065e05df914e95e7ca02f8ab))
- desktop: the mod = SUPER test checks the live layer's keys, not VECTOR's, which only exist where he's installed ([f4fb7fe](https://github.com/bromigos-org/bromigOS-archive/commit/f4fb7fea5ecba6da6dce0277e00e9b9d89429f97))
- desktop, homelab: bromigos memory clears VECTOR's notes in Gnosis too, archived first; undo files them again ([fd5997f](https://github.com/bromigos-org/bromigOS-archive/commit/fd5997f2f9be2c27cdecc362bfd7f31f9eb5b5bd))
- desktop: the theme previews draw nothing while NVIDIA's driver halves differ, and a run gives up after one GPU failure ([9f9ff3c](https://github.com/bromigos-org/bromigOS-archive/commit/9f9ff3c4b793d746ab11e85a67718e2c2ea69627))

### Live layer

- live: reduced motion: calm and still modes for the den, the worlds, the overlays and decks ([3705ee5](https://github.com/bromigos-org/bromigOS-archive/commit/3705ee5ee0e03b328186007cc1886bc9151d75fc))
- live: reduced motion: the intercept's crossfade from the frozen screen runs 0.9 s ([6a1feba](https://github.com/bromigos-org/bromigOS-archive/commit/6a1feba19acb2df8361892bee8f2f3458a640684))
- live: a mouse movement ends the screensaver again (an overlay's motion handler was shadowed) ([fba5688](https://github.com/bromigos-org/bromigOS-archive/commit/fba5688a7889b615d1b6cc314a5aabec5389e6af))
- live: the underlay loads at any screen width (a pixbuf's rows at their own stride; alpha over black) ([321b883](https://github.com/bromigos-org/bromigOS-archive/commit/321b883619b7cccbdfd2aa6835b8ce947f9fe072))
- live: one daemon per user, and stop/restart stop exactly it (by PID and start time, never pkill -f) ([d9872d5](https://github.com/bromigos-org/bromigOS-archive/commit/d9872d52bbb4f5e3ec63dd0292a9759b837858ca))
- live, desktop, homelab: nothing private ships: the lab's name, its nodes, the decks and the fills feed come from config and plugins ([cda67e8](https://github.com/bromigos-org/bromigOS-archive/commit/cda67e8fd93af2ceb214ea7992b06b2078028202))
- live: a zombie isn't a running daemon (stop and the tests, where PID 1 doesn't reap) ([2689bc2](https://github.com/bromigos-org/bromigOS-archive/commit/2689bc2751684c83ecbb710c39dbf6f3ff10ca84))
- live, desktop: the den follows a colour theme: its painted plate, its shaders' own greens, the burn-in, the wallpaper and the lock screen ([75a1285](https://github.com/bromigos-org/bromigOS-archive/commit/75a1285478632f56e5f552d43d65231e6d83f48f))
- live, homelab: the constellation's positions as a list of {node, at}, so an overlay encrypts every host name ([86cd139](https://github.com/bromigos-org/bromigOS-archive/commit/86cd139ea55d60394396acfb1d5c8afddb4b467b))
- live: the Drift map's lore catalog ships with the package and is the default (bromigos.org's public lore export); [driftmap] catalog still names another ([0eb9ddc](https://github.com/bromigos-org/bromigOS-archive/commit/0eb9ddcd295243506fa4c39b0dc8ff5638145834))
- live: the quick-launch ring's NOTES opens the FIELD NOTES panel, ready to type in, not nvim ~/notes ([1e3d023](https://github.com/bromigos-org/bromigOS-archive/commit/1e3d023c25bd1047b49363d26379d1ec29c072e7))
- live: on a software renderer (llvmpipe, softpipe, swrast) the background holds a still frame, decks at 10 fps, and says so once ([b9dec13](https://github.com/bromigos-org/bromigOS-archive/commit/b9dec13689ea2834b77a22e4ca24e09ddf877eda))

### Boot and the ISO

- iso: the installer adds this machine's hardware packages and services from the medium ([1b80a06](https://github.com/bromigos-org/bromigOS-archive/commit/1b80a06b4c7c8a5b7d760e4465a1088e1b7b7a62))
- boot menus: "tuning into the relay": a GRUB theme for installed systems, themed ISO menus ([e92a2c8](https://github.com/bromigos-org/bromigOS-archive/commit/e92a2c82d9c9052a0f767f52750d43d4082def8e))
- settings/grub: the boot theme's helper ignores the firmware's loader name in an install chroot (the live medium's, not the new system's) ([e475829](https://github.com/bromigos-org/bromigOS-archive/commit/e4758297d6f56d6d3f323955e7e3a77ea1a34f30))
- settings/grub: the boot menu's icons get a thin edge in the background colour, so the selected entry's reads on the phosphor bar ([8aec889](https://github.com/bromigos-org/bromigOS-archive/commit/8aec889b5277d831b53ce0eb74521bd96fe1306f))
- iso: the BIOS menu's font goes in the profile's grub/ (mkarchiso copies only syslinux's .cfg and splash); docs: the harness's boot-menu commands ([a03cc70](https://github.com/bromigos-org/bromigOS-archive/commit/a03cc70dec18ddd32fc26cc3289bf8f072a1fb8e))
- iso: Memtest86+ on UEFI again (memtest86+-efi 8 ships memtest86x64.efi, which mkarchiso 91 doesn't copy: the build puts it in grub/); iso/test.sh menu live presses no key ([d52bb6d](https://github.com/bromigos-org/bromigOS-archive/commit/d52bb6d8fa5ed4b4e042cb9ca900b675b4f9c4f4))
- settings/grub: the boot theme's helper syncs grub.cfg and /boot before it returns (a power cut leaves the old or the new); iso/test.sh boots the medium first by bootindex (after an install the firmware's own order puts the disk first) ([f8fdb3e](https://github.com/bromigos-org/bromigOS-archive/commit/f8fdb3eca0881af2ab2b46457f94f8df9f799ddd))
- boot menus: the medium's Boot from disk chainloads the disk's boot loader (else the firmware's next device); a snapshot's kernels say their microcode; docs: GRUB 2.16's firmware entries, the sync ([36933cf](https://github.com/bromigos-org/bromigOS-archive/commit/36933cf380e31e9e6425ecb6a834ef82f8c64f8c))
- settings/grub: on a BIOS the boot theme asks GRUB for 1024x768, then 800x600, before VBE's auto (640x480 without the screen's EDID); an older block is brought up to date by apply and the pacman hook ([bf84135](https://github.com/bromigos-org/bromigOS-archive/commit/bf841355803f97f45c710aad7fe6086f86307400))
- iso: Boot from disk connects the firmware's other disks (connectefi) and chainloads the first boot loader on another disk than the medium, archinstall's removable path too; the test wants the installed theme's bar ([3a8a572](https://github.com/bromigos-org/bromigOS-archive/commit/3a8a572416b553c9e0fb18158c6c0dbc69409b7e))
- iso: Boot from disk on UEFI reads the installed system's grub.cfg (a chainloaded GRUB lost its prefix: grub rescue), then other loaders, then the firmware ([6cf6288](https://github.com/bromigos-org/bromigOS-archive/commit/6cf62887f638daad4dddc45ab90664f69fa76abf))
- iso: the UEFI menu's screen-reader entry is back (the Boot from disk rework took it out) ([58f61dd](https://github.com/bromigos-org/bromigOS-archive/commit/58f61dddf5f3df954e27e51301608e811e20a96a))
- boot menu: the installed system's entries read "bromigOS Linux": GRUB_DISTRIBUTOR in the boot theme's block (10_linux names and classes the entries by it); off takes the block out, so Arch's own name is back, and /etc/os-release stays Arch Linux's; bromigos-settings' pacman hook (refresh) brings an older block up to date whichever theme is in /boot, and a migration retries it where the hook couldn't; status --json says block_outdated; the preview's installed menu named the same ([68ab3b0](https://github.com/bromigos-org/bromigOS-archive/commit/68ab3b06a24fe11a9fbe413f13325549456ccec7))
- boot menu: the VM runs for the entries' names (an installed machine updated, its pacman hook rewriting the block; a fresh install from a test medium, encrypted: live 16/16, installed 76/76, update and rollback 7/7; off and on again after reboots); the docs' picture of the installed menu taken again in Mire; no fallback initramfs on today's installs (one entry per kernel), and grub-install names its EFI folder bromigOS ([4380484](https://github.com/bromigos-org/bromigOS-archive/commit/4380484c1530aa907aec7011bf6292dd744a3451))
- iso: test.sh takes BROMIGOS_ISOTEST_MEM, the VM's memory in MiB (6144 by default) ([b59b6a8](https://github.com/bromigos-org/bromigOS-archive/commit/b59b6a89cd0570d64ae8e810c2edfb4d2c4ebdd2))

### Widgets

- widgets: SHORTCUTS calls Alt+Left and Alt+Right "Move split left" and "Move split right", not Narrower and Wider ([716ca5b](https://github.com/bromigos-org/bromigOS-archive/commit/716ca5b2046939436853119d5496e72f80f13d71))

### Themes and art

- themes: hologram models for the eight worlds, and the shared craft and relay ([50f6ee0](https://github.com/bromigos-org/bromigOS-archive/commit/50f6ee03e75d236010d7d5697ef3eb98c50dbd8a))
- art: create.toml may list several workflows per provider, tried in order ([9e51beb](https://github.com/bromigos-org/bromigOS-archive/commit/9e51beb235858c9a985647b70ed45e662444fcc0))
- art: video.loop on a ComfyUI: Wan 2.2 (TI2V-5B on the lab, I2V-A14B ready), model-agnostic ([ca5f11f](https://github.com/bromigos-org/bromigOS-archive/commit/ca5f11fb0e99630c1a76cf86633d3d37f349550d))
- art: a workflow the ComfyUI lacks files or nodes for, or whose card is too small, is skipped for the next ([e80771f](https://github.com/bromigos-org/bromigOS-archive/commit/e80771f4c5245054354e1791e59fc460306570b9))
- theme: the app launcher's icons: a bold glyph in the burn-in's ring, drawn in code per size ([79fd73f](https://github.com/bromigos-org/bromigOS-archive/commit/79fd73f7824be4c5a7cc0b3339f2c242993e3ab1))
- art, lab: cutouts on Lucida, 3D on Pixal3D (stood upright), and upscales of images and clips on SeedVR2 7B ([947713c](https://github.com/bromigos-org/bromigOS-archive/commit/947713c652b529f7e77e45185212a2631b8ab640))
- theme: mire: the Sleeper's eight clips sharpened with SeedVR2 7B on the lab ([7b111ce](https://github.com/bromigos-org/bromigOS-archive/commit/7b111ce751d089c6b61d55bb61e88f47684e0d58))
- art: a clip upscale asks an idle ComfyUI to unload its models first, so SeedVR2's temporal chunks get the whole free VRAM ([9ed6e44](https://github.com/bromigos-org/bromigOS-archive/commit/9ed6e44fee1299c5b717f3e72fd18f89deccdd23))
- themes, homelab: the hologram previews rendered again with demo readings: no lab name, no likeness ([843a992](https://github.com/bromigos-org/bromigOS-archive/commit/843a9921d78c2fd5328cd411726e5db7a9e928df))

### Homelab

- homelab: the lab console's seams: status cards, doctor checks, job kinds, the job queue ([823f562](https://github.com/bromigos-org/bromigOS-archive/commit/823f5629d891578e8d8c00d90cfb1bcda7c7df79))
- homelab: capabilities for the lab's own services (gpus, logs, routes, certs, ddns, network, storage, apps, games, library, runners, packages, backups, ocr) ([105fffe](https://github.com/bromigos-org/bromigOS-archive/commit/105fffe0b61835a2dcbd514096a1d9cbe889633b))
- homelab: the lab console's dashboard and its tests: status, doctor and the queue against a recorded lab ([3fe0e99](https://github.com/bromigos-org/bromigOS-archive/commit/3fe0e99064454eb6bba526473e847ad55d6dbe28))
- homelab: the lab dashboard's pilot tests and snapshot (Textual 8.2.8) ([091a867](https://github.com/bromigos-org/bromigOS-archive/commit/091a86785bdfbae0c616f1c4df45a9428518b89c))
- homelab: adapters for the rest of a lab: GPUs, logs, the edge, storage, games, the media library, AI services, CI, packages, backups ([5aee3ae](https://github.com/bromigos-org/bromigOS-archive/commit/5aee3ae2ae6f0206ae045c3c1d42c91dc08e688d))
- homelab: tests for the lab adapters and their doctor checks, against recorded (sanitised) answers ([6e49feb](https://github.com/bromigos-org/bromigOS-archive/commit/6e49febc787310d26ede1e8f4a747e3d0e448073))
- homelab: bromigos setup homelab detects the lab's services from its metrics and its cluster ([a7113a1](https://github.com/bromigos-org/bromigOS-archive/commit/a7113a1f6ce21de6ca92db60019ce3bc3b560f8c))
- homelab: the redis adapter counts a command's bytes, not its characters (RESP) ([3bccf53](https://github.com/bromigos-org/bromigOS-archive/commit/3bccf533d5d6f0943b61f064521e9c2c1ac397ab))
- homelab: a test: a kubeconfig that may not proxy to services leaves the source unreachable, saying why ([714385c](https://github.com/bromigos-org/bromigOS-archive/commit/714385c69481c70261d009cf197b1ad6ab122a38))
- homelab: bromigos lab: the console's command, its job queue's service, the Lab deck (SUPER+SHIFT+H), Settings › Lab ([6f0b7e4](https://github.com/bromigos-org/bromigOS-archive/commit/6f0b7e46659abf25f539c0b4012f4cbc4e94a596))
- video loops on the lab: the lab's video kind, the first run's targets, the docs ([2f84cda](https://github.com/bromigos-org/bromigOS-archive/commit/2f84cdaefe6f02e9fcb2f6299eea07ec9518dd5f))
- homelab: the Lab deck keeps its labels in the panel (a narrower orbit, shorter holds on the left) and shows a drilled card's values whole ([2e7605e](https://github.com/bromigos-org/bromigOS-archive/commit/2e7605ee79dd1ee260fb0a2a2b0e9c11036b86cc))
- homelab: the lab model catalog: the best open models per capability and GPU, a planner, upgrades, a weekly refresh ([e7b7d74](https://github.com/bromigos-org/bromigOS-archive/commit/e7b7d7482f52bc8b9289f4648218df8927fe0ebe))
- lab catalog: three licences corrected (GLM-Image, GLM-OCR: MIT; Granite Speech 5.0: Apache 2.0), and a quieter refresh ([e4f2714](https://github.com/bromigos-org/bromigOS-archive/commit/e4f2714e05ef98760a41d6f0a2d14fcdc0730971))
- lab catalog: where Actions can't open pull requests, the weekly refresh commits its tested change and files the report as an issue ([e9d36ff](https://github.com/bromigos-org/bromigOS-archive/commit/e9d36ffecf6ea24f3626583b288616fb0974fc26))
- lab catalog: weekly refresh 2026-10-09 (metadata and pending review entries) ([283c68b](https://github.com/bromigos-org/bromigOS-archive/commit/283c68b5dad0b86b7bd28dea93cacf653e8fcc2b))
- lab catalog: LLM serving figures from published benchmarks on the same hardware; agents' prompts and the server's sequence cap count; the licence region from the time zone ([0b52495](https://github.com/bromigos-org/bromigOS-archive/commit/0b52495a7ed07689547406c2afe8532f2f52fcbf))
- lab catalog: a family's newer member counts only under a pipeline the catalog covers; the three FLUX.3 action robot policies dismissed ([a75ef18](https://github.com/bromigos-org/bromigOS-archive/commit/a75ef185c55854aef84fcecf78c205ef42a934c8))
- homelab: the LAB panel finds the object store's NAS share in the snapshot (the share its claims are bound on), named as the lab names it, or "on the NAS"; no share name in the code, and the private-names check scans homelab/widgets for k8s_ share names ([ef32f7a](https://github.com/bromigos-org/bromigOS-archive/commit/ef32f7a2785af46563428cc2731db68b916fd9d0))
- lab doctor: a homelab target that fails behind the one a service uses is no finding ([b11d6a4](https://github.com/bromigos-org/bromigOS-archive/commit/b11d6a4c9a0ad0d7488f3e6176b0b5f2653ae9f5))
- homelab: bromigos lab moves with the arrows and Vim's keys: j/k between cards and rows, h/l between the STATUS panes, g/G, Ctrl+D/U, ] [ (L H) through the tabs; a tab's list takes the keyboard when it opens ([1bf4c1d](https://github.com/bromigos-org/bromigOS-archive/commit/1bf4c1dd4c05334d23c644af22ad59a2055b3f29))
- homelab: a heavy lab job short of VRAM asks an idle ComfyUI to unload, instead of waiting five minutes for the sidecar ([2d26919](https://github.com/bromigos-org/bromigOS-archive/commit/2d26919b23502a15360801decf217d556a4afdb8))
- homelab: the Proxmox fixture's VMs have made-up names ([71e5a0d](https://github.com/bromigos-org/bromigOS-archive/commit/71e5a0da43785244fdc0738749ef7aba94b164bb))

### Tests and tools

- test/vm: a second VM beside the first, and a faked notebook chassis for the hardware test ([63772cc](https://github.com/bromigos-org/bromigOS-archive/commit/63772cc772e7652d052a11220f6c7ed2baf6a395))
- iso/test.sh: the installed system's channel is checked against the medium's ([1cfa85d](https://github.com/bromigos-org/bromigOS-archive/commit/1cfa85dd64aadf1340e8f0e6ba75af63649f7e59))
- iso/test/live-checks.sh: /boot's mode is reported, not required ([4156364](https://github.com/bromigos-org/bromigOS-archive/commit/415636467e6f9dd182924126a30f3523d24ec2ad))
- desktop/tests: the shortcut picker: unit tests, offscreen renders, a nested end to end ([e85110e](https://github.com/bromigos-org/bromigOS-archive/commit/e85110e6342735bff21429fdab4683a93750a232))
- iso/test.sh: a run beside another (its own port and display), and extra QEMU arguments for a faked laptop ([a089a25](https://github.com/bromigos-org/bromigOS-archive/commit/a089a256bf073d412ab559120df45e2a2e120e8f))
- desktop/tests: the Settings registry's tests skip without GTK 4's bindings (the package builder) ([976d82b](https://github.com/bromigos-org/bromigOS-archive/commit/976d82bb408c7e0c37137b5e0e669b71d45e8166))
- desktop/tests: bromigos keys' undo, --json and list --all; the Settings page, drawn and driven ([98501ec](https://github.com/bromigos-org/bromigOS-archive/commit/98501ec6e99c89e9432a758812527fe517fedaef))
- desktop/tests: bromigos keys' tests pass on the package builder (no VECTOR, no xkbcommon) ([6e45d0e](https://github.com/bromigos-org/bromigOS-archive/commit/6e45d0ef4e2b8be20c7a431f438e8ed02b6c366c))
- test/vm: the fresh machine checks bromigos keys; docs: peripheral modules and the picker ([5f8da6a](https://github.com/bromigos-org/bromigOS-archive/commit/5f8da6a36ac7061c7b636353834e972c02c89f14))
- desktop/tests: bromigos keys' command tests verify with a stand-in Hyprland ([c69aa39](https://github.com/bromigos-org/bromigOS-archive/commit/c69aa39c4b85cc941ca9abb6e6d047d2368078c2))
- test/vm: idle and lock end to end (idle-e2e.sh); docs: idle: the VM run, 30/30 ([844a69e](https://github.com/bromigos-org/bromigOS-archive/commit/844a69e7a705904150a9cec5d0bc1bbeae059176))
- tools/settings/render.sh: the throwaway home gets a new user's hyprland.lua (the Shortcuts page reads it) ([a45c8da](https://github.com/bromigos-org/bromigOS-archive/commit/a45c8dacf172a949f7ee9260771f38444271d5b7))
- test/vm: the keys check reads bromigos keys' own key order (SUPER ALT CTRL SHIFT), and resets even when a step fails ([bd9c5c6](https://github.com/bromigos-org/bromigOS-archive/commit/bd9c5c676341ab509e5a7118783905176e6b678a))
- iso/test.sh: the boot menus: menu ENTRY (the medium's menu, then a channel booted and checked), grub NAME (the installed system's GRUB saved), up ([dfb0bc9](https://github.com/bromigos-org/bromigOS-archive/commit/dfb0bc944743a116f70eeb22c54d03a2be8f9ee7))
- desktop/tests: the stand-in bromigos pretends one built-in per file (fixtures/builtins/), else routes like the real one; renders fall through to the real CLI ([3599558](https://github.com/bromigos-org/bromigOS-archive/commit/35995588327a72eb4e2c5b22069d0c9ef589b04e))
- desktop/tests: Settings end to end in a nested Hyprland with a PipeWire nobody hears: Sound, 11/11 ([f7d5616](https://github.com/bromigos-org/bromigOS-archive/commit/f7d5616c5a159c6c55ff55827c64fff9d4eee4b6))
- desktop/tests: the network stand-in's addresses from the documentation ranges (RFC 5737) ([c62542b](https://github.com/bromigos-org/bromigOS-archive/commit/c62542b66f351cb4961dee87c21942e7313b4951))
- test/vm: Settings against the real services in the fresh-machine VM, 22/22; Breeze's names for five pages' icons ([d5661fc](https://github.com/bromigos-org/bromigOS-archive/commit/d5661fcabad732b7eead95b25bb073c5d27fca97))
- tools/screenshots: the loop's frames complete: Hyprland's animations off for the capture, and each picture taken again until it shows its frame whole ([795a11b](https://github.com/bromigos-org/bromigOS-archive/commit/795a11b56a2fa000ebfe4e8b90b4d56219b2f9b8))

### Docs

- docs: peripheral modules: the doc, the manual's page, the commands and their JSON ([f86bcd0](https://github.com/bromigos-org/bromigOS-archive/commit/f86bcd068de4111018d18f2baaebcab79d2eaf58))
- docs: PLAN: the peripheral modules batch is done ([156a489](https://github.com/bromigos-org/bromigOS-archive/commit/156a489eae3614e3550673d03de305fa78f74c5b))
- docs: ASSETS: the operator's decisions: lab-made holograms on the site, no AI captions ([166f843](https://github.com/bromigos-org/bromigOS-archive/commit/166f843be8c7e1ea0a0e1ded5f9be3e7f16d6e44))
- docs: the README and desktop/README name the peripheral modules ([e91238b](https://github.com/bromigos-org/bromigOS-archive/commit/e91238b0295aa4afaee8946354e9c21d72c52953))
- docs: ASSETS: the Seedream and Seedance assets are cleared by the operator's decision ([64a5d10](https://github.com/bromigos-org/bromigOS-archive/commit/64a5d1098c47092524a32ac319a3ce62bdef5197))
- docs: hardware: bromigos hw, the GPU matrix, laptops, the touchpad, what's proven; PLAN: the hardware batch is done ([6a8b664](https://github.com/bromigos-org/bromigOS-archive/commit/6a8b664f7169c6fac5227cb26bf343f7bae7eba6))
- docs: accessibility: the doc, the manual's page, the commands and their JSON; PLAN: the batch is done ([c487c0a](https://github.com/bromigos-org/bromigOS-archive/commit/c487c0a8a6d4001299a86c01368291ae9ababbeb))
- docs: ASSETS: every bromigOS and brand asset is cleared for shipping and the site (operator) ([99c638e](https://github.com/bromigos-org/bromigOS-archive/commit/99c638eec8320e5ab9ad91fc14fd35fa2efa9c46))
- docs: the v0.1.1 candidate's runs: the ISO (UEFI encrypted, BIOS plain) and the fresh machine ([ee5e5cb](https://github.com/bromigos-org/bromigOS-archive/commit/ee5e5cb56930f634f70cdd662a1dd86480f3e4ba))
- docs: install: the stable v0.1.1 fresh-machine run (install.sh's defaults, 40/40) ([81493c9](https://github.com/bromigos-org/bromigOS-archive/commit/81493c9aa986da7aaf8670e26428d1b72cdf7bbb))
- docs: idle and lock (docs/idle.md), Settings and its page registry (docs/settings.md), the manual's pages ([a9fadfa](https://github.com/bromigos-org/bromigOS-archive/commit/a9fadfa5b887b252f1f38f7c0c010c5415455cfe))
- docs: settings: the interaction check ([0c49e0e](https://github.com/bromigos-org/bromigOS-archive/commit/0c49e0e1f78ee0b981f8ff279382ea601a781d02))
- docs: the shortcut picker: desktop.md's Shortcuts, the manual's own keys, the menu, web apps ([0e1e4d5](https://github.com/bromigos-org/bromigOS-archive/commit/0e1e4d55092df34bb3424c754ed6f9beff2e5dfd))
- docs: README: the hardware batch (bromigos hw), and phase 4's batches done ([c6ace1b](https://github.com/bromigos-org/bromigOS-archive/commit/c6ace1b5ef4147f9a8ed6caacce78597bfdcb04c))
- docs: hardware: the ISO run (a faked notebook installed from a medium built with it) ([314e24b](https://github.com/bromigos-org/bromigOS-archive/commit/314e24b34d435edf86330b4b7f254a04f037ce99))
- docs: Settings' Shortcuts page, bromigos keys undo, list --all and --json ([965ca5a](https://github.com/bromigos-org/bromigOS-archive/commit/965ca5af62e9e33c325dba756bc27b005960c765))
- (withheld by the privacy check) ([b35d3a9](https://github.com/bromigos-org/bromigOS-archive/commit/b35d3a99672c809d73d870335c2e37f4171550e3))
- docs: the README opens on the Wick, and lists Settings, idle and lock, the shortcut picker and the work in progress ([6d19d3c](https://github.com/bromigos-org/bromigOS-archive/commit/6d19d3cbb2067762d01e3efda965e7b85b6a1339))
- docs: accessibility: VECTOR's holograms and construct follow the motion setting (vector ee0c832, bromigos-vector r32) ([7ebd3e0](https://github.com/bromigos-org/bromigOS-archive/commit/7ebd3e021ae1e50128b57092ec50be4ff2137912))
- docs: homelab: the lab's own services: their capabilities, the adapters (what each reads and what it powers), the doctor's checks, the ocr job; the manual's table ([33a5bb5](https://github.com/bromigos-org/bromigOS-archive/commit/33a5bb53e68d9b6316c4595afb70a588cbfd3133))
- docs: the lab console (docs/lab.md, the manual's chapter), provisioning's design (docs/lab-provision.md), the plan's phases 2 and 3 ([5ca9cf4](https://github.com/bromigos-org/bromigOS-archive/commit/5ca9cf4d37db825ff2fccfd9500ee308b6daa8c2))
- docs: lab: video runs on the lab now (Wan 2.2): the video kind, creature-loop, the shared jobs.toml ([2abd6e7](https://github.com/bromigos-org/bromigOS-archive/commit/2abd6e76aefe993b29800cc22454aee5b3ae0aba))
- docs: VECTOR's gallery shows the worlds' holograms, each on its world's shelf in its colours ([33e560b](https://github.com/bromigos-org/bromigOS-archive/commit/33e560b4ea6adecadc772f3fa459b95c88c95d0e))
- docs: the app launcher: every bromigOS window in it, what each entry runs, the menu listing each once, the tests ([d29bf71](https://github.com/bromigos-org/bromigOS-archive/commit/d29bf71db7095a31c9cfe5604b705a26325c4fba))
- docs: settings: the Lab page sits first in the Lab group ([d0819bd](https://github.com/bromigos-org/bromigOS-archive/commit/d0819bde35f50177558a815a792febc06fd1189d))
- docs: the commands reference: bromigos display, net, bluetooth, power, clock, notifications, defaults, startup, panels, memory, about, avatar; setup input's new options ([f27f6e1](https://github.com/bromigos-org/bromigOS-archive/commit/f27f6e1bcc4461a669c691ad94c676a3fc99bde9))
- docs: Settings: the window (groups, the search, the layout, Advanced, Undo, keys, sizes), every page and the command it drives, the API for a page or a section, the tests; the manual's chapter, a section per page (F1 opens it) ([c2cdd15](https://github.com/bromigos-org/bromigOS-archive/commit/c2cdd15ee76e721cc92e7d6d46e1eeddbb3cf36d))
- docs: settings: the VM run, 22/22, and what it can't reach (a virtual Bluetooth controller) ([282fe3b](https://github.com/bromigos-org/bromigOS-archive/commit/282fe3bd032f6112284bec811ca4da55145d7365))
- docs: settings-audit: the After column as built (Ctrl+1…6, narrow rows, the clamp, restyling) ([35ba84d](https://github.com/bromigos-org/bromigOS-archive/commit/35ba84d7ce4ad691c6f7e7397ba0461da6534a48))
- docs: the boot menus' VM runs: UEFI and BIOS, the medium's channels, the installed theme, what they turned up ([58d2616](https://github.com/bromigos-org/bromigOS-archive/commit/58d2616ae1dd3df38c24296754eef54857423fc8))
- docs: install: the fresh-machine run with the keys checks and the live layer's fixes (43/43) ([d64d1aa](https://github.com/bromigos-org/bromigOS-archive/commit/d64d1aac97a344320a3019a8ec3d2096703af1a7))
- docs: README status: the boot menus, the switcher's real previews, the den in colour themes and bromigos lab phase 1 are done; lab phases 2 and 3 planned ([bc78208](https://github.com/bromigos-org/bromigOS-archive/commit/bc782089a3c2658402b30b95448e0b9637a2b454))
- docs: VECTOR's emergency switch in Settings, on the bar and on SUPER+CTRL+ESCAPE; his guard records changes (bromigos vector guard log) instead of switching his terminal off ([06deb5c](https://github.com/bromigos-org/bromigOS-archive/commit/06deb5ce76c9427822c2d47bede57eb9121d03c1))
- docs: add WRITING.md, the guide every doc follows; AGENTS.md points to it ([cb967e9](https://github.com/bromigos-org/bromigOS-archive/commit/cb967e9fda861bd77e159074d9f8943316089e98))
- docs: add CONTRIBUTING.md: layout, build, test, docs and CI ([bf4fc1b](https://github.com/bromigos-org/bromigOS-archive/commit/bf4fc1b5914490fd549d58acb0cdf4299de8d56c))
- docs: rewrite the docs index by topic ([3f85d90](https://github.com/bromigos-org/bromigOS-archive/commit/3f85d906fd624fbb79a32d0e25743ece98edd632))
- docs: images for the README and docs; ASSETS.md as a short checklist with provenance below ([1cab690](https://github.com/bromigos-org/bromigOS-archive/commit/1cab690e257154128f43b40bc10664fbad6ee484))
- docs: rewrite install, update, ISO, encryption and boot pages in plain words ([b4f5cee](https://github.com/bromigos-org/bromigOS-archive/commit/b4f5cee3001896f2e292c77aaaa67eeeacb1037c))
- docs: rewrite theming, worlds and art pages; unbuilt world features marked Planned ([25f2192](https://github.com/bromigos-org/bromigOS-archive/commit/25f2192b86a2fcd9538f91e58f8634c43f3000bf))
- docs: rewrite the desktop, Settings, idle, accessibility, menu and app pages ([a75b92f](https://github.com/bromigos-org/bromigOS-archive/commit/a75b92f103558901c476d77897ba3615fcc9996e))
- docs: rewrite the homelab, lab, model catalog, provisioning and targets pages ([8a6ed48](https://github.com/bromigos-org/bromigOS-archive/commit/8a6ed48743c07652cd1f28978bf0420b4d4a57bc))
- docs: rewrite the extension, plugin, widget, peripheral and hardware pages and the starters' READMEs ([cf35d0a](https://github.com/bromigos-org/bromigOS-archive/commit/cf35d0ab873f94cf45c3aaa9b6ad62b76298da4e))
- docs: rewrite the core, packaging and brand READMEs; add the missing JSON schemas ([3684612](https://github.com/bromigos-org/bromigOS-archive/commit/3684612273dbf9171df3055c8e8874a378eafacb))
- docs: rewrite the live layer, elements and hologram READMEs ([42be161](https://github.com/bromigos-org/bromigOS-archive/commit/42be161d5bbfdb36bb0fc57add6c2c74d4d749f7))
- docs: PLAN.md as a readable plan and decision log ([12bf7f8](https://github.com/bromigos-org/bromigOS-archive/commit/12bf7f8cccfabb1207f9a55cf3a1fc686cd3c1f3))
- docs: README rewritten for someone deciding whether to try bromigOS ([3632acf](https://github.com/bromigos-org/bromigOS-archive/commit/3632acf55c81a99cb14f23de402221e8fbe14e19))
- docs: mark the passages where VECTOR's guard switches his terminal off by itself ([ac10e5b](https://github.com/bromigos-org/bromigOS-archive/commit/ac10e5b4815cc1550c3f68da24ef2f0b899ed691))
- docs: README's hero and theme grid re-exported; the whole LAB widget beside the homelab section ([05ec87c](https://github.com/bromigos-org/bromigOS-archive/commit/05ec87c1a3417d56f66b30b76b5b42efc6a6f55f))
- docs: ASSETS.md: the manual's pictures as one row, listed below the table ([e2e917c](https://github.com/bromigos-org/bromigOS-archive/commit/e2e917c9837ae58d8317c075e101256c756d43f4))
- docs: links follow the manual's new outline: page titles, What gets installed, manual-reference.toml ([ddf7541](https://github.com/bromigos-org/bromigOS-archive/commit/ddf75413a6240b9003085869682ccef405b97fca))
- docs: the Drift map's lore catalogue ships with bromigos-live; its ASSETS.md row in the new layout ([9f596bf](https://github.com/bromigos-org/bromigOS-archive/commit/9f596bf670d6f705c409c9701bf506668674fc2c))
- docs: upscales on SeedVR2, cutouts on Lucida and 3D on Pixal3D in the rewritten art, lab, targets and catalog pages ([0b9c704](https://github.com/bromigos-org/bromigOS-archive/commit/0b9c704ccd3e15c6ce6534810d1e23139d6a10cc))
- docs: VECTOR's emergency switch and the guard's audit log in the rewritten pages ([cc02367](https://github.com/bromigos-org/bromigOS-archive/commit/cc0236733f88ed8e9741bfe5a99c7e7cbfa38e66))
- docs: ASSETS.md: the manual's Welcome picture in the list ([f117a76](https://github.com/bromigos-org/bromigOS-archive/commit/f117a762f8b7ef0ebc895180e4a51d0cd3fcafa3))
- docs: ASSETS.md: the manual's 27 pictures, with the new render set ([35958c6](https://github.com/bromigos-org/bromigOS-archive/commit/35958c62e07f6ee8733f52f7fe2c4082ca7bf1ea))
- docs: README: the full render set, the Tidewell loop near the top, and VECTOR, the menu and bromigos lab in the grid ([5e742f0](https://github.com/bromigos-org/bromigOS-archive/commit/5e742f0314a028324c56dcfb39dfc60b65b2f909))
- docs: the docs index and CONTRIBUTING.md link release.md, CHANGELOG.md and the release workflows ([e730432](https://github.com/bromigos-org/bromigOS-archive/commit/e7304329b5c2d2cd6cc3d51d1519c4cbc7b66fa3))
- docs: README: the loop under the header and the final renders; CONTRIBUTING.md lists tools/screenshots/render.py ([1a87ea4](https://github.com/bromigos-org/bromigOS-archive/commit/1a87ea4a785b5bc5071214899758e34c101ff588))
- docs: the AUR (docs/aur.md): paru, AUR packages in bromigos update's snapshot pair, the review, turning it off, drivers only the AUR has; the VM runs ([c4eb8d5](https://github.com/bromigos-org/bromigOS-archive/commit/c4eb8d52e5f21e83a31b6902268b74adae4465f6))
- docs: the AUR in the rewritten pages: paru at install, AUR packages inside the update's snapshot pair, bromigos aur, AUR-only NVIDIA drivers ([0992673](https://github.com/bromigos-org/bromigOS-archive/commit/0992673779c15079ac625a290ef31a621b2d9d32))
- docs: the package note says 1password repackages 1Password's own download; only herdr and paru are built from source ([028674f](https://github.com/bromigos-org/bromigOS-archive/commit/028674f0c63c2b56bfbd2141d5a453f4af8f43b3))
- docs: release: a known limitation: one web manual, built from main, for every channel; each machine's installed copy matches its packages ([0fecefc](https://github.com/bromigos-org/bromigOS-archive/commit/0fecefc39d3bc44c351248dc83868dc8190068ed))
- docs: the README's Tidewell loop without its flicker: 41 frames the capture rendered without the glow pass, rebuilt from their neighbours ([029b5a3](https://github.com/bromigos-org/bromigOS-archive/commit/029b5a3da5612ecdb568ca135a90c0828eaa473f))
- docs: the README's Tidewell loop deflickered: each frame's lighting matched to the median of the nine around it (some frames were captured brighter than their neighbours too) ([b7bab4e](https://github.com/bromigos-org/bromigOS-archive/commit/b7bab4edaec2b0d57d97a81406159804b3ffbb0a))
- docs: mark the sections bromigos.org reads with <!-- site:… --> comments, so a rewrite can rename them without breaking the site's export ([02e93cb](https://github.com/bromigos-org/bromigOS-archive/commit/02e93cb27d5075b27111e6eec3623753333b98f1))
- docs: SECURITY.md and issue templates ([8374841](https://github.com/bromigos-org/bromigOS-archive/commit/8374841c73ff42f28abe2203a0d9bb5e6dc060f1))
- docs: VECTOR proposes changes as pull requests from his own clones (manual: VECTOR); CODEOWNERS names the operator for the code behind his limits (made from VECTOR's devflow.LIMITS: his merge tool leaves those PRs to you) ([5282cb1](https://github.com/bromigos-org/bromigOS-archive/commit/5282cb1cb526687ff617ebc71852243cc6b0e7ae))
- docs: the README's Tidewell loop rendered again with the capture fixed: every frame whole, no hand repair (120 frames at 960 wide, 1.6 MB) ([d26f41a](https://github.com/bromigos-org/bromigOS-archive/commit/d26f41a5829131062fefff638c296cb3d2956095))
- docs, manual: Mire on the desktop rendered again, with the Sleeper's sharpened clips (7b111ce) ([4b30a91](https://github.com/bromigos-org/bromigOS-archive/commit/4b30a91269fa4e8b34329d979a6ddb8c748e70f1))
- docs: when the kernel or the graphics driver changes: what the update holds back, the live layer's guard, the previews, and the test runs ([60e17ca](https://github.com/bromigos-org/bromigOS-archive/commit/60e17ca354503303320e95dce77b50e71e4019bc))

### Packaging and CI

- ci: iso-check looks for each boot channel's own menu entry, not the word anywhere ([b47009f](https://github.com/bromigos-org/bromigOS-archive/commit/b47009f856414ac777bf5050134224902c0f5236))
- packaging: a tag's publish copies a package another channel has, signed, instead of building it; release tags only from main ([1af68e1](https://github.com/bromigos-org/bromigOS-archive/commit/1af68e1ea70c2588b133a3316ab0d0e7cc08a024))
- ci, docs: releases from GitHub Actions: prepare (notes by the homelab's model, git-cliff's changelog, the release PR), cut on merge, promote rc to stable ([9ce87cd](https://github.com/bromigos-org/bromigOS-archive/commit/9ce87cd63541f891aeefd15b4c382db733920fff))
- packaging: paru, the AUR helper, built into [bromigos] (2.1.0-2, the AUR's recipe with its alpm crates pinned) ([8755140](https://github.com/bromigos-org/bromigOS-archive/commit/875514055fbe6e62b1e03425122aa0a28900bd20))
- ci: the release workflows upload their artifacts with upload-artifact v7 (v4 runs on the deprecated Node 20) ([27a9f07](https://github.com/bromigos-org/bromigOS-archive/commit/27a9f070ba6bb8f26721f5b6d0de04b56bccd553))
- ci: pull requests run on GitHub's hosted runners, never the homelab's ([021ad58](https://github.com/bromigos-org/bromigOS-archive/commit/021ad58214ed84fbeca5265fa9dcd911193c392d))

### Other

- manual: a new outline (getting started, using bromigOS, reference), a glossary, and the Keys and Commands pages grouped by task in plain words ([f52aa31](https://github.com/bromigos-org/bromigOS-archive/commit/f52aa315e13ae877ded5bde1311e586b5174c227))
- manual: getting started rewritten for a new user: Welcome, Install, First run, Getting around, The menu, Windows and workspaces, and a Common tasks page ([579b030](https://github.com/bromigos-org/bromigOS-archive/commit/579b0307d0a704d7df4f84b2e7e5fbf6216f4f96))
- manual: every chapter rewritten in plain words and checked against the code, with new Holograms and Your own shortcuts chapters ([7223bf6](https://github.com/bromigos-org/bromigOS-archive/commit/7223bf6091072ee508ff2e7f350f104350ffb10d))
- manual, docs: pictures next to the steps: the desktop with callouts, the nine themes, the worlds, the screensaver, the gallery, the launcher and eight Settings pages; ASSETS rows for each ([72b00ed](https://github.com/bromigos-org/bromigOS-archive/commit/72b00ed181962499f9ce3825b54db4201b9b1842))
- code comments: the doc sections they cite, by the names the docs rewrite gives them ([da5a0a1](https://github.com/bromigos-org/bromigOS-archive/commit/da5a0a14dc21e233043428540eff1f16dd45404f))
- manual: the desktop on the Welcome page; a colon chain and two semicolons split; VECTOR's brain may not be chosen yet ([6d9123c](https://github.com/bromigos-org/bromigOS-archive/commit/6d9123ce15b39394b868a9da149598b7291a6c3a))
- manual: lab upscale jobs (SeedVR2, built today) and the two upscale services in where AI runs ([1d8c1da](https://github.com/bromigos-org/bromigOS-archive/commit/1d8c1da7eba8d8773908233573ce17af917ba42b))
- manual, docs: the offscreen render set on its pages: the menu, VECTOR, Settings, the theme switcher, Cinder, Mire and Tidewell on the desktop, the holo deck, the timeline, the Drift map, bromigos lab and both boot menus; an ASSETS row each ([04c6ef1](https://github.com/bromigos-org/bromigOS-archive/commit/04c6ef12c41d645ea318bd95dc6b847b0f72406d))
- manual: VECTOR's emergency switch (Super+Ctrl+Esc, the bar's power mark, Settings, bromigos vector off|on) replaces the kill switch; the guard only logs (bromigos vector guard log) ([ba76a56](https://github.com/bromigos-org/bromigOS-archive/commit/ba76a561048bf4758c1103de4b6f9d457b43a2aa))
- manual: What's new's introduction in the manual's style, and linked from Updating and rolling back ([34a06e6](https://github.com/bromigos-org/bromigOS-archive/commit/34a06e675f8520e2fbbe7ef1d0a4dd2c8adb5f03))
- tools: screenshots/render.py, the README's and the manual's pictures drawn offscreen: the desktop in scenes (the hero, the worlds, colour themes), the nine themes as one sheet, VECTOR, the holo deck, the timeline, the Drift map, the menu, Settings, the switcher, bromigos lab and the boot menu, an animated loop of a world behind the panels; every picture read back with tesseract against the words none may show (and the private overlay's names) before it's kept; the switcher's render takes a --backdrop ([a57e121](https://github.com/bromigos-org/bromigOS-archive/commit/a57e121bc4469b0031d31604db66325ddf956fb3))
- test: aur-e2e.sh, the AUR in the fresh-machine VM: a fresh install, an opted-out one, a machine with the AUR's own paru ([1d4c10c](https://github.com/bromigos-org/bromigOS-archive/commit/1d4c10c9dbd6cc87e6278404ab8d239a995af7aa))
- manual: the AUR: installing an app with paru and reading its recipe, AUR packages in bromigos update, the first run's AUR question, --no-aur at install, an older NVIDIA card's driver through hw setup, and a glossary entry ([3de762a](https://github.com/bromigos-org/bromigOS-archive/commit/3de762a7cd8f2c3ca5ab1d4dc515d165af719551))
- test: the VM harnesses' QEMU stops when the session that started it ends ([c491733](https://github.com/bromigos-org/bromigOS-archive/commit/c4917339a82bca3591a4887f891cb29c9f13438e))
- tests, tools: the private-name checks no longer spell the names they look for ([2d80486](https://github.com/bromigos-org/bromigOS-archive/commit/2d80486f0b2dc74aecea4b88dae94f780987d9cb))

### VECTOR (bromigos-vector)

#### Added

- The holograms follow bromigOS's motion setting (accessibility.toml: full, reduced, still) ([ee0c832](https://github.com/bromigos-org/vector-archive/commit/ee0c8321fc8bab2efc52b95abfc638783b340dbf))
- The lab console for VECTOR: lab_console, lab_jobs, lab_job_submit, lab_job_cancel; his terminal reads bromigos lab and refuses what changes the lab ([c5f67cb](https://github.com/bromigos-org/vector-archive/commit/c5f67cb496585edcc2635558b9a997ad33b667d3))
- VECTOR and the hologram gallery in the app launcher: desktop entries with their icons, and gallery-show (opens, never a toggle) ([d6f66cb](https://github.com/bromigos-org/vector-archive/commit/d6f66cbf7cc7b82e64af5ff74a67dfd3b758123c))
- The worlds' holograms in the gallery, shelf by shelf, each in its world's colours ([39145cc](https://github.com/bromigos-org/vector-archive/commit/39145cc46327fe990faf9c1a829a3937934bd9aa))
- The lab's settings are read-only to him: ~/.config/bromigos/lab.toml (the model planner, the upgrade policy, the catalog bench) ([76a1a50](https://github.com/bromigos-org/vector-archive/commit/76a1a50e1afec7901162f871c2ae8f3b5d5ec27e))
- The operator's emergency switch (bromigos vector off|on, SUPER+CTRL+ESCAPE, the bar, Settings); Changed: the guard's sentinel only audits, it never switches VECTOR off ([988f945](https://github.com/bromigos-org/vector-archive/commit/988f945b58402330addabd247667af69179d8c06))
- VECTOR's own clones and pull requests (work_clone, work_status, work_branch, work_commit, work_push, pr_open, pr_watch, pr_merge, pr_close; bromigos-holo work) as his GitHub account bromigodev; pr_merge never merges a PR that touches the code behind his limits (devflow.LIMITS, CODEOWNERS) ([4f6d14e](https://github.com/bromigos-org/vector-archive/commit/4f6d14e09ad7cd2acfbe967dd844b9047e10a918))

#### Changed

- His homelab making follows the lab's new models: cutouts are Lucida, 3D is Pixal3D (shape only, stood upright), and lab_job_submit's upscale takes an image or a short clip (SeedVR2 7B) ([f235825](https://github.com/bromigos-org/vector-archive/commit/f235825cf70c63b3115c16985d0cdc7901da4e12))
- VECTOR names no one's trading system: a user's own system comes in through plugin hooks, and their real money through vector.toml [real_money] ([6f3e202](https://github.com/bromigos-org/vector-archive/commit/6f3e202737c3ea6c2f1926f029fdd52a11599dc0))

#### Fixed

- The state file is written before VECTOR's scene exists (voices and colour empty until then), not a traceback at startup ([09218bf](https://github.com/bromigos-org/vector-archive/commit/09218bfd037aa0777bf0bb319e8f659f54423423))
- A voice change publishes VECTOR's state at once, so a keyboard dial steps through every voice (it read a stale mode and only ever reached the first and last) ([ee3fbdf](https://github.com/bromigos-org/vector-archive/commit/ee3fbdf12bc88a805059547773431b321a0f0d8d))
- The privacy guard reads a list's lists in a sops file (- - ENC[…]) as encrypted, not as plaintext values ([cb51f48](https://github.com/bromigos-org/vector-archive/commit/cb51f48b9377513e3d3a56e8843edcefc2bd368f))
- The guard's notice says his terminal stays off until you run bromigos-holo shell on, not until he's restarted (a restart leaves it off) ([897ab9e](https://github.com/bromigos-org/vector-archive/commit/897ab9e74b49bf73bbd4a31032a95324f7a31ec0))
- Bromigos-holo stop now stops at once (the launcher dropped "now"); stop and restart [now] return once the daemon has gone, so restart during a turn starts a new one; a started daemon no longer holds the caller's output open; the usage names the real verbs (history, voice by its key) and evals has no timer ([9c05dd4](https://github.com/bromigos-org/vector-archive/commit/9c05dd42db6dd4716be2b976d4f4e6e4027d288d))
- Pr_merge merges by rebase, so his commits land on main authored by bromigodev's noreply address (a squash merge was authored with the account's own email) ([4375763](https://github.com/bromigos-org/vector-archive/commit/437576378bf2b9365c050f03cc94ff193f310e80))
- The privacy guard's sops test uses made-up node names ([1a26563](https://github.com/bromigos-org/vector-archive/commit/1a2656334df76c65bdbf67cd5558eaabf1f47b91))
- Test-plugin-systems.py's child keeps this user's pip packages (CI installs them with --user) ([8cff3a7](https://github.com/bromigos-org/vector-archive/commit/8cff3a7983246e1392cc2a546081ddfc4eb85e38))

#### Docs

- docs: reduced motion in the holograms: what each setting changes, how still frames are drawn, the tests ([49a21e9](https://github.com/bromigos-org/vector-archive/commit/49a21e91846f2e9c7df22ca0c8f7a1806e153f69))
- docs: VECTOR for a newcomer: a task-first README with a console render, and docs/ pages for safety, configuration, tools, holograms, interfaces and development ([9f8b5d7](https://github.com/bromigos-org/vector-archive/commit/9f8b5d77ebf29f3cfcb602ee385194c4d95b528f))
- docs: the emergency switch (where it is, what off does, why it works with VECTOR hung, why only you switch him on, its files) and the guard as an audit log ([f04a3b8](https://github.com/bromigos-org/vector-archive/commit/f04a3b83b55b12f5ec80f57b3e489bd43e1f3277))
- docs: CHANGELOG.md, the technical log release by release (v0.1.0, v0.1.1 from the tags) ([806bab0](https://github.com/bromigos-org/vector-archive/commit/806bab071023af5e21cfb73be5a2c811b3490e78))
- docs: SECURITY.md, issue templates and the brand assets' licence ([db5ce4a](https://github.com/bromigos-org/vector-archive/commit/db5ce4a890180edbb0fd8daa34109747234c76ed))
- docs: his pull requests (safety.md: his clones, his account, what his merge tool never merges and why it's the enforcement; tools.md; development.md: test-devflow.py and the PR checks; README) ([3a51b95](https://github.com/bromigos-org/vector-archive/commit/3a51b9594e8944a595f9df1c408a9b4c193a0b31))
- docs: README: the guard audits his safety code, it doesn't switch him off (#3) ([fadb522](https://github.com/bromigos-org/vector-archive/commit/fadb522a870efa7f11c2ce50d40932ae99c52667))
- docs: propose-a-change: when his terminal refuses a test script for what its text names, he says so and lets CI run it ([67f98a8](https://github.com/bromigos-org/vector-archive/commit/67f98a8a0e3a9716ef8af5d0a7bcc7e502529681))
- docs: the hologram previews rendered again over the empty den with made-up readings (offscreen.py OFF_DEMO=1) ([ef1a550](https://github.com/bromigos-org/vector-archive/commit/ef1a5502091165d36d462f4f9d9259016332e94a))

#### Packaging and CI

- packaging: ship every docs page in /usr/share/doc/bromigos-vector, not only plugins.md ([b80b2dd](https://github.com/bromigos-org/vector-archive/commit/b80b2dd438e9795699d5b8680feee2ed856e4cef))
- packaging: a tag's publish copies bromigos-vector from another channel, signed, instead of building it; release tags only from main ([ac0863a](https://github.com/bromigos-org/vector-archive/commit/ac0863ace01293fdb00c87050091b925e2621758))

## [0.1.1] - 2026-10-08
<!-- release: 0.1.1 -->

Since v0.1.0.

### Core (the bromigos command)

- core: bromigos update starts the OSD when it's installed but not running, and restarts it when stale ([d7e3d77](https://github.com/bromigos-org/bromigOS-archive/commit/d7e3d775d3733de8afc640a21d75923ee98e6072))
- install: the rollback step's pacman doesn't stop to ask under --yes ([23d9d59](https://github.com/bromigos-org/bromigOS-archive/commit/23d9d59ebdf588dbad900e18242a3585cfd5a775))
- cli: bromigos update --check prints the OSD's 'start' (fixes the build after d7e3d77) ([e77713a](https://github.com/bromigos-org/bromigOS-archive/commit/e77713a3ae2f7caa9686777c13f5ff82d443411d))
- core: bromigos ext, extensions from git (manifest, ledger, trust, updates, starters) ([8047425](https://github.com/bromigos-org/bromigOS-archive/commit/804742565c628ebc93cfed162071c974a796a7ce))
- core: a channel switch drops the old channel's sync database ([cdc78af](https://github.com/bromigos-org/bromigOS-archive/commit/cdc78af001f4b43f0e6efe27ba289b3422b8a111))
- core: rollback: GRUB seen without /boot, wheel may list root's snapshots, the overlay hook, an install chroot ([88556a2](https://github.com/bromigos-org/bromigOS-archive/commit/88556a234ecb7814d7f5513420074b4949deb610))
- core: rollback status: a systemd initramfs can't take the overlay hook, so setup isn't asked for it ([6903a3f](https://github.com/bromigos-org/bromigOS-archive/commit/6903a3f5dc604ddff1a9f00babb5f58e589e2209))
- core: rollback setup sees an arch-chroot: its root mount isn't PID 1's ([db950b8](https://github.com/bromigos-org/bromigOS-archive/commit/db950b8b7ba8e6831ee1aafdadae93c7bbc18bd7))

### Desktop

- desktop: the theme switcher asks bromigos ext for catalog themes directly (it's a built-in, not an executable) ([72e3a15](https://github.com/bromigos-org/bromigOS-archive/commit/72e3a15b9ebc658448fbed43b865756463c763a2))

### Boot and the ISO

- iso: GRUB, LUKS2 by default, btrfs with snapper, the stable channel; the install tested end to end ([7b730d9](https://github.com/bromigos-org/bromigOS-archive/commit/7b730d9bbca938afb53799a765b883e6a9ddb825))
- iso: the installer sets up rollback with `bromigos rollback setup`; the harness proves it as the user ([c4ab3be](https://github.com/bromigos-org/bromigOS-archive/commit/c4ab3be9effb5731df919d6792ff9e54a09e3f94))

### Tests and tools

- test/vm: the app bundle's checks run (they sat after the exit) ([d85c321](https://github.com/bromigos-org/bromigOS-archive/commit/d85c321f0382f94d8405b3ff0c201c5bb8491632))
- test/vm: shellcheck: ext_repo is called through check (declare -f) ([d703de2](https://github.com/bromigos-org/bromigOS-archive/commit/d703de29e8192d731bc9d1b37bd4ee8fdbe25873))

### Docs

- docs: extensions (the author's guide), the manual's page, plugins, theming, PLAN ([39603df](https://github.com/bromigos-org/bromigOS-archive/commit/39603dfcea148e0c227b4d3b7c8aab230cd85bac))
- docs: the command reference, key table and package tables are generated, and CI checks them ([91a3448](https://github.com/bromigos-org/bromigOS-archive/commit/91a344857625c26e8eec764105b41efb9a445e24))
- docs: a whole documentation run: the README, docs/ by topic, the manual, the folder READMEs ([5f05a5a](https://github.com/bromigos-org/bromigOS-archive/commit/5f05a5a1cd00629516536c2dee2c54d4c48777b7))
- docs: PLAN: phase 3 is complete; the update -> rollback VM run is done (the ISO's) ([6c3d163](https://github.com/bromigos-org/bromigOS-archive/commit/6c3d1634dd792f5d9da6c2b7139ce20c1c3635f1))
- (withheld by the privacy check) ([c05e6d9](https://github.com/bromigos-org/bromigOS-archive/commit/c05e6d9c28863275ca21dfb6280ea786b1a1dc0c))
- docs: ASSETS: the world art, den and holograms are cleared under their model terms; the ByteDance clips are not ([36a3c48](https://github.com/bromigos-org/bromigOS-archive/commit/36a3c4821e231f20f01397f13846f5e2e6883a9a))

### Packaging and CI

- ci: docs: build the CLI with two jobs and no debug info (the small runner ran out of memory) ([555a28d](https://github.com/bromigos-org/bromigOS-archive/commit/555a28d9114713d35d016efd72f6275ed0376680))
- ci: docs: the command reference's cargo build runs on the package builder with its own cache ([c286208](https://github.com/bromigos-org/bromigOS-archive/commit/c286208246b761592dd370d30df2a2939b2dd1b1))

### VECTOR (bromigos-vector)

#### Added

- His state file names his voices and the colour of the one in use ([afc7592](https://github.com/bromigos-org/vector-archive/commit/afc75921634700644bfe838974b6987bf9187456))

#### Changed

- VECTOR's guard knows extensions: it accepts only what bromigos ext recorded, and he can't install them ([cfa24e2](https://github.com/bromigos-org/vector-archive/commit/cfa24e2f87388272ead7b08780fc0f5b3be76808))

#### Docs

- docs: VECTOR as a product: the README, the guard as it is, the skills index ([8682f23](https://github.com/bromigos-org/vector-archive/commit/8682f23423fd498ef3e8ed0172f8c7d319ddf5b9))
- docs: the guard watches extensions' plugin and homelab links, not skills ([437b771](https://github.com/bromigos-org/vector-archive/commit/437b77160b03ea9152fee43076adbe92455bde61))

#### Packaging and CI

- ci: one packages concurrency group per channel, so a tag's stable publish isn't cancelled by pushes to main ([bbf4da4](https://github.com/bromigos-org/vector-archive/commit/bbf4da48e1710b8d30a61b85752a863b6eed694e))

## [0.1.0] - 2026-10-08
<!-- release: 0.1.0 -->

The first release.

### Added

- BromigOS plan, asset checklist and agent rules ([529eeb2](https://github.com/bromigos-org/bromigOS-archive/commit/529eeb2306fe4c1ce344dc9ae9f2d9b29f5f186d))

### Changed

- Audience is the Bromigos community first; no feature regressions on the operator's desktop ([d1f20dc](https://github.com/bromigos-org/bromigOS-archive/commit/d1f20dccda96932eb0c85be51c574da23700c726))
- PLAN.md and ASSETS.md against the desktop as it is today — an inventory of every piece (VECTOR's brain, memory, voices, read/desk/shell/act/Vault/herdr tools, change tracking, skills, the holograms, the Razer module) split into core and plugin; status line (planning, nothing moved yet); memory, web search and default voice as open decisions; asset rows for the starship, avatar, sound cues, designed caretaker voices, skills and Razer files, with the Brodec cast as a personal plugin; README target rows ([a36354a](https://github.com/bromigos-org/bromigOS-archive/commit/a36354a8d822fd8be533ea72713eef2b921e4878))

### Core (the bromigos command)

- core: Rust core library and bromigos CLI ([0bacbae](https://github.com/bromigos-org/bromigOS-archive/commit/0bacbaea70ecd37fe3dd42045f51ccc207a7faf3))
- core: end quietly on a closed pipe (SIGPIPE default); ci: set PACKAGER ([c0c10ed](https://github.com/bromigos-org/bromigOS-archive/commit/c0c10ed472369515d9ab96cacdd5b705ff333d03))
- core: bromigos profile, who the user is and what VECTOR calls them ([87bb360](https://github.com/bromigos-org/bromigOS-archive/commit/87bb3604c2696b43af48d8c0072923aad17f9614))
- core: profile values edited by hand that break the rules read as absent ([ab63e9f](https://github.com/bromigos-org/bromigOS-archive/commit/ab63e9f85642e507825789c7bafcdc1cb8239449))
- core: bromigos theme list|current|set renders the theme with minijinja and swaps it in atomically ([c05892b](https://github.com/bromigos-org/bromigOS-archive/commit/c05892b4640690b58ca3806b3f2ef1494450b5ea))
- core: theme set brings a world's backgrounds/ and live/ into current/ and tells the live layer ([4262030](https://github.com/bromigos-org/bromigOS-archive/commit/42620308b10f553cbd5bd56bd5619b8b2baeaed0))
- core: bromigos art plans, makes and tracks a world's art through the nolgia SDK ([80c4a6a](https://github.com/bromigos-org/bromigOS-archive/commit/80c4a6aadd87d69144c837569f9c2c635247bb1f))
- core: the nolgia SDK on the system's OpenSSL, so the package builds with makepkg's flags ([9969b24](https://github.com/bromigos-org/bromigOS-archive/commit/9969b24073075014b086217ec781af1a80e41e95))
- core: theme set recolours everything: palette.json, the bar's icons, hooks ([c00ccbd](https://github.com/bromigos-org/bromigOS-archive/commit/c00ccbd639c8f205ef88ae468a644df446be1759))
- core: the worlds test reads a flyby's sprites from its craft ([40bde0e](https://github.com/bromigos-org/bromigOS-archive/commit/40bde0eda914931139b1a75fb9dba29e35665b12))
- core: bromigos vector uses the packaged bromigos-holo (bromigos-vector) when installed ([a0e8f01](https://github.com/bromigos-org/bromigOS-archive/commit/a0e8f01242e7a13cf7d98beba2e22f2d77db4fc6))
- install: install.sh, bromigos install, bromigos setup, and the bromigos meta-package ([2442459](https://github.com/bromigos-org/bromigOS-archive/commit/2442459105e5062c3446243c4b72b0ac7f77971d))
- core: bromigos setup homelab runs bromigos-homelab's detector; with --homelab/--answers FILE the built-in copy ([e57b70d](https://github.com/bromigos-org/bromigOS-archive/commit/e57b70dfd10285e9129973b3ca8af7b88ab00857))
- core: bromigos private, secrets and emblem; the brand's shareable sources in brand/ ([4c7a926](https://github.com/bromigos-org/bromigOS-archive/commit/4c7a9261f47358da8df11085b1070ff92458bf23))
- core: the session tests wait for their fake process to exec (a flaky check() broke a publish) ([6668f44](https://github.com/bromigos-org/bromigOS-archive/commit/6668f44949ed232900f9ba89c8672743efc4bfd4))
- setup: monitors (primary, order, scale, refresh) in the user's hyprland.lua; creation tools (create.toml format 1) ([d17847f](https://github.com/bromigos-org/bromigOS-archive/commit/d17847f8d134c9b9c9d5b45f3809c58af4b54025))
- update: replace the hand-installed theme files bromigos-settings now ships, instead of failing ([0026b20](https://github.com/bromigos-org/bromigOS-archive/commit/0026b2086ce52f844fc9223193f26a4d87c79b51))
- core: bromigos update no longer hangs after restarting a daemon ([9bb349f](https://github.com/bromigos-org/bromigOS-archive/commit/9bb349f3246bc7716a696c5c244faecc351c26b9))
- core: bromigos update restarts VECTOR's voice server too ([1cf3208](https://github.com/bromigos-org/bromigOS-archive/commit/1cf3208681be0381b2e7e90323b3638d7c581973))
- setup: nolgia sign-in without a terminal (--nolgia-token-file / nolgia_token_file) ([3e91596](https://github.com/bromigos-org/bromigOS-archive/commit/3e915960e72e722a487b790c7578b50da38f3c92))
- core: where AI runs: targets.toml (homelab, local, cloud) and bromigos target ([0e80938](https://github.com/bromigos-org/bromigOS-archive/commit/0e80938c0be34def9f9ef8db2a097b2d58d4e2c3))
- migrations: the start page waits for an old user unit to go, then enables the packaged timer ([b8515bd](https://github.com/bromigos-org/bromigOS-archive/commit/b8515bd1973d6646c02262ed1d3812603b73f87c))
- core: theme set and bromigos update restart waybar instead of reloading it ([ede8fb0](https://github.com/bromigos-org/bromigOS-archive/commit/ede8fb05a897210ffbb6cc0b98705864289dc211))
- core: bromigos theme install <git url|dir> and remove; bromigos mute says it on the OSD ([b0aca7c](https://github.com/bromigos-org/bromigOS-archive/commit/b0aca7c5059372d098df5cb28af17d29c1d932d2))
- update: a snapshot around every update and --rollback; channels (stable, rc, edge, dev); the manual ([10788b4](https://github.com/bromigos-org/bromigOS-archive/commit/10788b4d78e85a93c0896df04e50d8d2bd5e09a8))
- core: bromigos channel aligns its channel list ([6d1dd8e](https://github.com/bromigos-org/bromigOS-archive/commit/6d1dd8e5d11ce2c6eddf830930735fb795a3ec45))

### Desktop

- desktop: the desktop's configs ship as defaults (bromigos-desktop); bromigos update with migrations ([a824c16](https://github.com/bromigos-org/bromigOS-archive/commit/a824c1665836c7e7bde3ce9a80e2d788ab158ccf))
- desktop: the hooks, the wallpaper tool and the Wick's den ship; the session's plumbing is declared ([0cb44e1](https://github.com/bromigos-org/bromigOS-archive/commit/0cb44e197906e31e2cfec11a9e1d9929bf5bb1b0))
- settings: bromigos-settings, what exists before a user does ([4545204](https://github.com/bromigos-org/bromigOS-archive/commit/45452046a83ee8c43d73aed155be7fcb5bb1a1c4))
- settings: the login screen is Bromigos's (zz-bromigos.conf, read after sddm's own default.conf) ([9a1491a](https://github.com/bromigos-org/bromigOS-archive/commit/9a1491a38e6e548e6b9fd160991a2328cc56f352))
- desktop, live, widgets: monitors are plug and play ([df61095](https://github.com/bromigos-org/bromigOS-archive/commit/df61095302f2977e44d34803c23fcf26c498e906))
- wallpaper: one swaybg restart at a time (login's apply and monitor.added raced: two per output); test/vm: --heads N, shot NAME [HEAD] ([79e9fc0](https://github.com/bromigos-org/bromigOS-archive/commit/79e9fc0fe7332a86689f06a567fe09afeaa97c49))
- desktop: hotplug, tested: workspaces split in place and fold back; the wallpaper follows unplugs ([693855c](https://github.com/bromigos-org/bromigOS-archive/commit/693855cf9aeae77214e48bb9b41e30fc4e499d8d))
- desktop: the start page ships (bromigos-desktop): a self-contained per-user folder, the lab from bromigos-homelab, links from startpage.toml ([c58b622](https://github.com/bromigos-org/bromigOS-archive/commit/c58b622ca2debef536a6c06f7a74422e448c0857))
- desktop: the lock screens name the packaged emblem hook's path ([c09f19f](https://github.com/bromigos-org/bromigOS-archive/commit/c09f19f3b8f5eef787d614760fb1c8637460756b))
- desktop: the start page's folder can be set in startpage.toml (dir), so an existing browser setup keeps its path ([ae2f9e1](https://github.com/bromigos-org/bromigOS-archive/commit/ae2f9e1ecb7f76a4bae36d563e861b050bcc186f))
- desktop: one mute for the whole desktop (bromigos mute): the theme's sounds and VECTOR's voice together ([84901ef](https://github.com/bromigos-org/bromigOS-archive/commit/84901efdd03ceac365946509dd23539e1062e25a))
- desktop: the bar pip's middle-click is the desktop mute (theme + VECTOR) ([b913e28](https://github.com/bromigos-org/bromigOS-archive/commit/b913e281b92d812fa5e21a391b82852fcccf6d18))
- desktop: the bar pip's middle-click mutes VECTOR alone again; bromigos mute is the keys' and the dial's ([d33ffc3](https://github.com/bromigos-org/bromigOS-archive/commit/d33ffc3af21a47ca6f11be3a312548ee44bdf59d))
- settings: the Bromigos boot splash (a Plymouth theme from the emblem kit) ([891a8e7](https://github.com/bromigos-org/bromigOS-archive/commit/891a8e744d5ee12f7d58fbccfa93de77fed23d82))
- desktop: the bar's VECTOR pip says MUTED, not VOICE MUTED, when the desktop mute is on ([eacb286](https://github.com/bromigos-org/bromigOS-archive/commit/eacb286ae35ee7a6b32b781d260ab09be6d42a25))
- desktop: floating windows go back where they were, per workspace and app (bromigos windows) ([7e8eb45](https://github.com/bromigos-org/bromigOS-archive/commit/7e8eb4506916eca760f44ce70700ce62a04dcd04))
- desktop: the menu (SUPER+SPACE), the theme switcher, web apps, setup menus and the OSD ([917d0c8](https://github.com/bromigos-org/bromigOS-archive/commit/917d0c882bc28f54ae3991e33a91ab5e2df97d3a))
- desktop: a command places itself in the menu (bromigos:menu=, bromigos:prompt=); the switcher lists a catalog's themes ([ab8dca2](https://github.com/bromigos-org/bromigOS-archive/commit/ab8dca2fa864038a62e8589a4a7bfa191ac26731))
- desktop: the start page snapshot copies through a private temporary name ([48d4779](https://github.com/bromigos-org/bromigOS-archive/commit/48d477952dc3c476cf2264553d3f61237b158d02))

### Live layer

- live: worlds -> Wick: the den's glyph rain came up in the last theme's colour ([47c66b2](https://github.com/bromigos-org/bromigOS-archive/commit/47c66b29bff949c5c72b1d84598ad5cd4d6e83f6))
- live: a crowd's per-member art (sprites = [...]) is glow art too: no box around it ([82ff2d9](https://github.com/bromigos-org/bromigOS-archive/commit/82ff2d9f633279ccc01314e09f8a1ba68401b001))
- live: VECTOR from the installed package (bromigos-vector) or the dotfiles' copy, and steps aside without him ([cccf789](https://github.com/bromigos-org/bromigOS-archive/commit/cccf789a56c19475ae2297659382be87943f2e0e))
- live, widgets, wallpaper: the output is this machine's, not a hard-coded DP-1 ([b4e4fcb](https://github.com/bromigos-org/bromigOS-archive/commit/b4e4fcb84fd06f596b12510ac2b9bb6884796c07))
- live: no DP-1 fallback for the activity watcher (the resolved output, or none) ([f1e9767](https://github.com/bromigos-org/bromigOS-archive/commit/f1e976709baa60e089e79ddb1964651fe2611db6))
- live: config.toml layers merge (packaged, then the user's thin file); menus and screenshots in the theme's colours ([2cf0e09](https://github.com/bromigos-org/bromigOS-archive/commit/2cf0e097e2dbdb8873fdc2a235b41b2980e11b86))
- live: screens that aren't 16:9 get the scene cropped to cover them, never stretched ([42d6a66](https://github.com/bromigos-org/bromigOS-archive/commit/42d6a6656ac927c02fda04b3ca415e1e1ad071a5))

### Boot and the ISO

- iso: the bromigOS live and install medium (archiso's releng with bromigOS on top) ([e4fc4a1](https://github.com/bromigos-org/bromigOS-archive/commit/e4fc4a182a03d13143576c7bb7710353a6607129))
- iso: the install is btrfs on LUKS2 by default, Limine boots it, snapper's snapshots in its menu ([c3c85e0](https://github.com/bromigos-org/bromigOS-archive/commit/c3c85e0e8e2a4d185aac39181b17198b881c8d00))
- iso: the installer reads find's limine.conf paths with a while loop (shellcheck SC2044) ([9208d96](https://github.com/bromigos-org/bromigOS-archive/commit/9208d96c15a7f9906b61a60aa15776b33aa25208))
- iso: the offline repository's sign options as archinstall names them (Optional, TrustedOnly) ([c2ddfc1](https://github.com/bromigos-org/bromigOS-archive/commit/c2ddfc1a02612536aa329988e867c24d642703be))
- iso: no second [bromigos] section for pacstrap; the offline copy carries what archinstall straps on its own ([b6a4679](https://github.com/bromigos-org/bromigOS-archive/commit/b6a4679acf307477ac704855be924bd2628af789))

### Widgets

- widgets: a weather panel (Open-Meteo) and a NetworkManager panel, off by default ([5be597c](https://github.com/bromigos-org/bromigOS-archive/commit/5be597c301585b9686e51bb616a52414346c09a7))

### Themes and art

- theme: wick, the first theme, as data; templates for waybar, gtklock, rofi, kitty, dunst, Hyprland, KDE ([756efc4](https://github.com/bromigos-org/bromigOS-archive/commit/756efc4a45450ce5cbff6981a86a1cccdff8b778))
- theme: mire and tidewell, the first worlds, with placeholder art; the world format ([e94125c](https://github.com/bromigos-org/bromigOS-archive/commit/e94125cf0912eb638cf4da9e6c9240fdebcd4c7f))
- theme: tidewell seen from under the surface; mire's keeper clear of the lantern ([4a4c403](https://github.com/bromigos-org/bromigOS-archive/commit/4a4c403fc33a761a55d6763a7c3f09656b2c7533))
- theme: mire and tidewell fitted to the approved comps; Sleeper heads in Mire's foreground; worlds.md mapping ([c68874c](https://github.com/bromigos-org/bromigOS-archive/commit/c68874c25da13f779c97695b7c897738c70b1ceb))
- theme: mire and tidewell describe their art in art.toml, seeded from the first pass ([2afef00](https://github.com/bromigos-org/bromigOS-archive/commit/2afef00af4a01bb5dc176c8b8ec3b9b5137a8f2b))
- theme: mire's Sleepers rise and submerge with their agents; live fireflies; one-shot clips in the format ([9689b30](https://github.com/bromigos-org/bromigOS-archive/commit/9689b30855864f765aff76c3e897133b933c7152))
- theme: mire and tidewell real art: approved comps, layers, actors, loops and Sleeper clips ([3ba639a](https://github.com/bromigos-org/bromigOS-archive/commit/3ba639ab397043f6752a7cd251224c8d1f2f8c79))
- theme: mire and tidewell run on the real art; the placeholders go ([0a92993](https://github.com/bromigos-org/bromigOS-archive/commit/0a929937c8ec097fa0e75a9ccf7cf43af8db880a))
- theme: mire's art log records the hand clips and Hollis's loop as made ([de6cfe8](https://github.com/bromigos-org/bromigOS-archive/commit/de6cfe86b1054795ed336a0c2c1b07c8f3e3632a))
- theme: mire keeps Hollis's loop on the GPU at half size (it is drawn at 204x221) ([28fc415](https://github.com/bromigos-org/bromigOS-archive/commit/28fc41550b88e0c4c054786033b866eeabe33457))
- theme: tidewell: the nets trail behind the trawlers, real silver fish, no moored ship ([3ad0946](https://github.com/bromigos-org/bromigOS-archive/commit/3ad0946f393032d8fb1bbe83fce2b870bae4389a))
- theme: mire and tidewell: craft overhead, now and then, sooner with network traffic ([dbdd549](https://github.com/bromigos-org/bromigOS-archive/commit/dbdd549a700bf0fac679f55f28531aed1d9778c2))
- theme: each world's post has its own emblem (Mire's and Greywater Light's marks) ([fa791c0](https://github.com/bromigos-org/bromigOS-archive/commit/fa791c0beb4fd77cd00f6cd5658939160c8d60c8))
- theme: tidewell: every craft overhead passes behind Greywater Light, sized and hazed as farther off ([f50869f](https://github.com/bromigos-org/bromigOS-archive/commit/f50869ff22e41fc74d9c5eeb8e4059b4c30f0ba1))
- theme: tidewell: the Choir waits under the water and breaches now and then, not every 8 s on top of it ([904d473](https://github.com/bromigos-org/bromigOS-archive/commit/904d473d103c0735eea6c09d50ba02fa5b0c2405))
- theme: mire: rain from the work going on: agents drizzle, the homelab's models rain, CPU pours ([0d5f08f](https://github.com/bromigos-org/bromigOS-archive/commit/0d5f08f4331d707e88c1f2ab461258c4e41b99c2))
- theme: tidewell: its own sea life (lampfry, veilwings, burrs) instead of fish; the painted fish painted out ([38955b1](https://github.com/bromigos-org/bromigOS-archive/commit/38955b19e2ac6cae81a78c7dce65805027513967))
- theme: tidewell: the lampfry spread into three loose shoals, drifting slower ([3750190](https://github.com/bromigos-org/bromigOS-archive/commit/3750190c62923bb198d9667929fbea225cbb6463))
- theme: mire and tidewell: the unlock intercept takes the world's look ([64d9481](https://github.com/bromigos-org/bromigOS-archive/commit/64d9481ca1cb02773f23b218a08bd2300f9ddcaf))
- theme: tidewell: the whole water to the Sliver's flank, resident jellyfish, linebloom ([d13f2a7](https://github.com/bromigos-org/bromigOS-archive/commit/d13f2a779886eee6e7109391e1c4514ec3ff44e6))
- theme: tidewell: the Choir glows: brighter at work, brightest when it needs you, dim when done ([c9c99bd](https://github.com/bromigos-org/bromigOS-archive/commit/c9c99bd1315d7488be2cad3258be41610f97a6b6))
- theme: tidewell: the resident jellyfish in pink, orange, violet, cyan, mint and gold ([80c57eb](https://github.com/bromigos-org/bromigOS-archive/commit/80c57eb45d94e8d57dffe0ed50aaa48efa069852))
- theme: tidewell: linebloom in its own colours: violet, pink, orange, gold and cyan, calmer ([25913ed](https://github.com/bromigos-org/bromigOS-archive/commit/25913ed96db59a29c5aed5d704dbff8d83c25121))
- theme: tidewell: the healthy linebloom bright enough for its colours to read ([0f50f2c](https://github.com/bromigos-org/bromigOS-archive/commit/0f50f2c3ed41cee8350a0e93fc3cb230312e4050))
- theme: tidewell: the linebloom holds steady instead of throbbing ([5f18189](https://github.com/bromigos-org/bromigOS-archive/commit/5f1818935f070000195b90d7f26cf3d8858869b4))
- theme: tidewell: the healthy linebloom's own breathing barely there (±4%) ([739f7f9](https://github.com/bromigos-org/bromigOS-archive/commit/739f7f99e998a216454df5968319ee71c9dc6978))
- theme: tidewell: the resident jellyfish are two-tone: a primary and a contrasting accent ([cb25658](https://github.com/bromigos-org/bromigOS-archive/commit/cb256584973d7e1a6881d79aa2e7acdace62294f))
- theme: tidewell: the rose jellyfish's cyan arms hang down its centre ([0a88ff6](https://github.com/bromigos-org/bromigOS-archive/commit/0a88ff6142609764af46057b6c428c65335a8da2))
- art: a homelab backend: model = "homelab:qwen-image-2.1" runs on the user's ComfyUI for no credits ([f9227aa](https://github.com/bromigos-org/bromigOS-archive/commit/f9227aa9a9bb625d95b36d00fddb60343a1594a7))
- theme: the bar icons' builder (theme/tools/build-icons.py) moves in from the operator's dotfiles ([60f677a](https://github.com/bromigos-org/bromigOS-archive/commit/60f677a67a44140eac4f7e01b4ad8db47eeb40b0))
- art: creation providers (create.toml), local cutout and 3D, bromigos art make ([9f515e9](https://github.com/bromigos-org/bromigOS-archive/commit/9f515e944552ab30aa7f42ee7872f08c2d0e59e3))
- art: a nolgia 3D job has no paid texture pass unless asked; art make --extra KEY=VALUE ([da3a879](https://github.com/bromigos-org/bromigOS-archive/commit/da3a879c9ed5424332018c3e21d0a182eca5638e))
- theme: reaches neovim, btop, tmux, Chromium, Firefox and the OSD; six colour themes from the Drift ([6fa1327](https://github.com/bromigos-org/bromigOS-archive/commit/6fa132746ee6687baae0ebe67f3a48e2d9d9e7e4))
- theme: the OSD's stylesheet is swayosd.css (the shell batch's); the duplicate osd.css template goes ([cee6cfa](https://github.com/bromigos-org/bromigOS-archive/commit/cee6cfac553612c035cc80c771a6e0e6b5e32528))

### Homelab

- homelab: bromigos-homelab: connect any homelab to the desktop (capabilities, adapters, setup, declared panels) ([cd80dc4](https://github.com/bromigos-org/bromigOS-archive/commit/cd80dc4cc188ab978f89a26753b33bfa6d39e49f))
- homelab: the rack hologram ships with bromigos-homelab (shown with a homelab configured) ([bb078ea](https://github.com/bromigos-org/bromigOS-archive/commit/bb078ea34b6e8405098e420c0d926c1f14102665))
- homelab: voice and media capabilities (bromigos-voice and comfyui adapters) ([4cc43c1](https://github.com/bromigos-org/bromigOS-archive/commit/4cc43c10290437c0ea3e39a6d601f5bccfc4c8ad))
- homelab: Proxmox and Netdata adapters (hosts, workloads; metrics, hosts), tested on recorded answers ([42c14b5](https://github.com/bromigos-org/bromigOS-archive/commit/42c14b5f04e3da9bf4c52cd478c376903bdd0d8b))

### Apps

- apps: bromigos-apps, the app bundle: LazyVim, tmux, lazygit, mise, Chromium, Spotify, Signal (1Password built into the repo) ([9a8e1b0](https://github.com/bromigos-org/bromigOS-archive/commit/9a8e1b0f8c2f60a70dc8be4c917b54dd20f9afcd))

### Tests and tools

- test/vm: the CA copied writable (a second up), the SDDM check passes shellcheck ([e8d1894](https://github.com/bromigos-org/bromigOS-archive/commit/e8d18949880754b9922918101ebfbe5d467d6e4d))
- test/vm: --heads N gives N outputs (a virtio GPU each: QEMU leaves a second head of one GPU disconnected without a display client) ([5e6282f](https://github.com/bromigos-org/bromigOS-archive/commit/5e6282fda2ba0821e82edeb5be4e9236707e4603))
- test/vm: the fresh-machine test can install optional packages (BROMIGOS_VM_WITH) and checks the app bundle ([ac09278](https://github.com/bromigos-org/bromigOS-archive/commit/ac09278736e69218d1c7cb0d34df32ccf27d0c77))

### Docs

- docs: the repo is bromigOS ([71fb0d9](https://github.com/bromigos-org/bromigOS-archive/commit/71fb0d971223034520ba6ba7e2a92c01b3cfda78))
- (withheld by the privacy check) ([2f60731](https://github.com/bromigos-org/bromigOS-archive/commit/2f607315cc831c5092defcda56cd4f6c89a293f6))
- docs: decisions: MIT OR Apache-2.0, local-first brain, designed default voice, configurable SearXNG, SQLite memory; licenses added ([87e06e6](https://github.com/bromigos-org/bromigOS-archive/commit/87e06e6bb3ee8a60ec3a395546f29c83e48bd699))
- (withheld by the privacy check) ([a5c1bf6](https://github.com/bromigos-org/bromigOS-archive/commit/a5c1bf64f67fc4099703f2a8f55f4982a1a22300))
- docs: worlds: the view from each post, its keeper, and the real data every inhabitant shows ([59ae2fd](https://github.com/bromigos-org/bromigOS-archive/commit/59ae2fdfaf2b09be55dd11185434fea9bde71a15))
- docs: worlds: Tidewell is mostly underwater, Greywater Light small on the Sliver ([4cc07c1](https://github.com/bromigos-org/bromigOS-archive/commit/4cc07c18234c7d2f426679456480793d635cee3a))
- docs: worlds: Mire centres on the shack, with a crashed gunship and wreckage ([084e3be](https://github.com/bromigos-org/bromigOS-archive/commit/084e3be594ec34f3ffe6532268c9289e14f6e2be))
- docs: PLAN: VECTOR is packaged (bromigos-org/vector, bromigos-vector); what stays in his core ([905ce41](https://github.com/bromigos-org/bromigOS-archive/commit/905ce41565a086e4e0fd2b65d71e27bb6722a71f))
- docs: what bromigOS is about (holograms, homelab integrations, themes, widgets); bromigos-homelab closes phase 1 ([43f5c97](https://github.com/bromigos-org/bromigOS-archive/commit/43f5c97a9f812b6b33e29535de533290d8184806))
- docs: install.md (install.sh, bromigos install and setup, the packages, the VM test); the VM script passes shellcheck ([144305f](https://github.com/bromigos-org/bromigOS-archive/commit/144305f1e3d010102c2ea48f381ad5d98c734af0))
- docs: art: create.toml (format 1): capabilities, provider ids, endpoints and references, workflows, art make ([dd86d0f](https://github.com/bromigos-org/bromigOS-archive/commit/dd86d0f7336c2b88ac3fa7c1df59e0b9980db414))
- docs: monitors are plug and play (desktop.md); setup monitors and create, and the VM run's results (install.md) ([e788e99](https://github.com/bromigos-org/bromigOS-archive/commit/e788e99cf3bf59ad690e72497af03306e4ea85e1))
- docs: PLAN: phase 2's progress (a fresh install works end to end; what's left) ([fd81679](https://github.com/bromigos-org/bromigOS-archive/commit/fd8167945adfb0a754e5451610463fb6921667c3))
- docs: what the fresh-machine VM test needs to run in CI (KVM, ~8 GiB) and why it waits ([63178f3](https://github.com/bromigos-org/bromigOS-archive/commit/63178f3c48a8d4d7f1dfa142d66ceebebd3f339b))
- docs: PLAN: phases 1 and 2 complete (lock screens and live config thin, start page packaged, cover fit, unattended nolgia, Proxmox/Netdata); follow-ups listed ([39a21a2](https://github.com/bromigos-org/bromigOS-archive/commit/39a21a2d6988abc86eb56993091129120ec7f99c))
- (withheld by the privacy check) ([97f218c](https://github.com/bromigos-org/bromigOS-archive/commit/97f218c49279a3d84ecf249e8486799a5f6b3e60))
- docs: the theme's new outputs and colour themes, the weather and connections panels, windows, the app bundle ([4508a54](https://github.com/bromigos-org/bromigOS-archive/commit/4508a54e3a5acc30cb9d489c78a6841901da637b))
- docs: PLAN: the reach batch is done (themes past the desktop, six colour themes, weather and connections, windows, the app bundle) ([c8cd137](https://github.com/bromigos-org/bromigOS-archive/commit/c8cd13729c844ef7c8954af926a6c95f1fa790c8))

### Packaging and CI

- packaging: bromigos-keyring, bromigos-core, publish and setup scripts ([5376b0e](https://github.com/bromigos-org/bromigOS-archive/commit/5376b0ec91c15d8a97ee4bfe624376172eddd618))
- ci: build, sign and publish packages on push to main ([28249ef](https://github.com/bromigos-org/bromigOS-archive/commit/28249ef538f41549d6e862609999318020cb35c8))
- packaging: the live layer and the widgets move into bromigOS (bromigos-live, bromigos-widgets) ([bba3164](https://github.com/bromigos-org/bromigOS-archive/commit/bba31645254aa8f3cada5e7919280bba6b6e8337))
- packaging: CI installs only build-time dependencies (bromigos-live depends on bromigos-core) ([e75d3ee](https://github.com/bromigos-org/bromigOS-archive/commit/e75d3eea2b4953ac233c6f769c08b30b9110a193))
- packaging: bromigos-live and bromigos-widgets make no -debug package ([3b7cb10](https://github.com/bromigos-org/bromigOS-archive/commit/3b7cb10a9502c532d977d039440a9faafa31f372))
- packaging: one publisher at a time across repositories (a lease in the bucket) ([a186b60](https://github.com/bromigos-org/bromigOS-archive/commit/a186b6038c620dd12eec042f6b5169c38cb610b9))
- packaging: Geist Mono, built into bromigOS's repository (ttf-geist-mono) ([73db314](https://github.com/bromigos-org/bromigOS-archive/commit/73db31440260bfb843f1454ee43669cbf3ea13a6))
- packaging: bromigos-settings builds again (gresource is glib2-devel's; Pillow for the cursors) ([488b8d2](https://github.com/bromigos-org/bromigOS-archive/commit/488b8d2c2fc15fcad8c962c55c5ae3de98453eb6))
- ci: install.sh's smoke test; publish on settings/ and install.sh; the fresh-machine VM test ([dfb8a20](https://github.com/bromigos-org/bromigOS-archive/commit/dfb8a2004c74a4d9a88653940dda18646df22877))
- packaging: herdr, built into bromigOS's repository ([a77dcaa](https://github.com/bromigos-org/bromigOS-archive/commit/a77dcaae16cd50918d39cb975cbff55eca8aae31))
- ci: cargo's registry and bromigos-core's target persist in the runners' node cache ([ab0c68d](https://github.com/bromigos-org/bromigOS-archive/commit/ab0c68d7a7980cd0207b23778052a039ccf8cd88))
- ci: iso-check's bash steps run in bash (the runner's default shell is sh), with file_permissions declared as mkarchiso does ([0d90324](https://github.com/bromigos-org/bromigOS-archive/commit/0d9032474e26e60ce1a905b4adf9fc8930143076))
- packaging: bromigos-desktop ships bromigos-windows and starts it at login; bromigos-apps is an option of the meta-package; CI builds on apps/ ([16e99d0](https://github.com/bromigos-org/bromigOS-archive/commit/16e99d04ada9372526cb92958ca7b8c743b73f6f))
- packaging: bromigos-desktop ships bromigos-windows and starts it at login; CI builds on apps/ ([8658815](https://github.com/bromigos-org/bromigOS-archive/commit/8658815e26c30fc0890e93c12230b08d7c9a466a))
- ci: one packages concurrency group per channel, so a tag's stable publish isn't cancelled by pushes to main ([4ae00b5](https://github.com/bromigos-org/bromigOS-archive/commit/4ae00b54673f00122f0ebb23ab2a1f6dbd6a130a))

### VECTOR (bromigos-vector)

#### Added

- Bromigos-vector, VECTOR as a bromigOS package ([95dd61b](https://github.com/bromigos-org/vector-archive/commit/95dd61b1c0d980c3f183d34644a9f6d3204cddc6))
- VECTOR's hologram models ship with him; the tools take a collection (--root) ([b4ce347](https://github.com/bromigos-org/vector-archive/commit/b4ce3478555a3cd605cc41d442cab05ed0578f08))
- VECTOR speaks and listens through the lab first (engine lab), his own GPU only as the fallback ([4b7a3ad](https://github.com/bromigos-org/vector-archive/commit/4b7a3adb7ddf23f8f51bca51f138e951cdbbd953))
- VECTOR makes images, cutouts, 3D meshes and holograms on the homelab, never a paid provider on his own ([a1b448e](https://github.com/bromigos-org/vector-archive/commit/a1b448e87fa2a5b4dd0392e0842aff177cedbe8a))
- VECTOR's voice, hearing, brain and creation follow bromigOS's targets.toml (homelab, local, cloud) ([bb26d64](https://github.com/bromigos-org/vector-archive/commit/bb26d644238d5e07ef3580001b1d5b8cafccb34e))
- VECTOR's input box grows with what you type (up to 8 lines, then scrolls) ([1834fde](https://github.com/bromigos-org/vector-archive/commit/1834fde9bbe1b1bc4eb65c5cb851a21b16172cc3))
- VECTOR's mute takes on|off|toggle|status (for bromigos mute, the desktop's one mute) ([c627475](https://github.com/bromigos-org/vector-archive/commit/c6274751be15868529c751022728125493bd9cec))

#### Changed

- VECTOR from the operator's dotfiles (linux/.config/bromigos/holo at c136274) ([4ef0b1e](https://github.com/bromigos-org/vector-archive/commit/4ef0b1e365463732e8eba7a485ddca8cff86ce36))
- The operator's voice-cast tool (make-refs.py) from the package; it lives in his dotfiles ([b602414](https://github.com/bromigos-org/vector-archive/commit/b6024149d7053d3db8c204435704b044436b7369))
- The homelab read tools out of VECTOR's core into bromigos-homelab's VECTOR plugin ([c11de54](https://github.com/bromigos-org/vector-archive/commit/c11de548a4f254a67ca527f2077c5e07ea7e9938))
- VECTOR keeps his connections to the lab voice alive (a small pool), so a line doesn't pay a TLS handshake ([959b468](https://github.com/bromigos-org/vector-archive/commit/959b468409f499fd7ee58319dc4dcc2b66dd90e3))
- VECTOR's mute tooltip: the pip's middle-click mutes all sound (theme + VECTOR) ([9b7776f](https://github.com/bromigos-org/vector-archive/commit/9b7776f6ebfeb56fe71c4b3cfe4e4d74532362ff))
- VECTOR's mute tooltip: the bar pip mutes him alone; the keys mute all sound ([87d21d7](https://github.com/bromigos-org/vector-archive/commit/87d21d74e6a5b8c534e9e193e446c13e1da7b722))

#### Fixed

- The guard names paths.py and llm.py by path only (common names elsewhere) ([63300f1](https://github.com/bromigos-org/vector-archive/commit/63300f15c2bf87de639a595f2716f525eac9d6a6))
- Bromigos-holo's help lists evals and setup ([40cd472](https://github.com/bromigos-org/vector-archive/commit/40cd4725595045aa91107e9f24184ad5b8f87eba))
- The hyprland-config skill describes bromigos-desktop's layout (defaults in /usr/share, the user's thin hyprland.lua) and the auto-reload rule ([9662820](https://github.com/bromigos-org/vector-archive/commit/966282017f0b49b4b1d719cd07ed69074a199d0a))
- The build loop changes Hyprland's config without tripping its emergency mode ([92342ee](https://github.com/bromigos-org/vector-archive/commit/92342ee321bd321e0e60466c1bd39116a51e6702))
- A reading whose name has a digit (wick.solar2) is known to make-holo and the gallery's source map ([7515bc0](https://github.com/bromigos-org/vector-archive/commit/7515bc0ed71b589accf919c6667baebb4f63b548))
- With the lab voice up, the local cast voice no longer loads onto his GPU ([164e9bf](https://github.com/bromigos-org/vector-archive/commit/164e9bf48a10ae590aa61a153634c0fe31a8cecf))
- The guard's tripwire watches what VECTOR runs, and accepts verified package updates ([521a3b0](https://github.com/bromigos-org/vector-archive/commit/521a3b0e1e0885ff2bda5fe10f8c4159a3b7dfeb))

#### VECTOR

- holo: the hologram's output is bromigOS's primary, not a hard-coded DP-1 ([f381d67](https://github.com/bromigos-org/vector-archive/commit/f381d6724641a0513efd2240b944cca0e83c5429))

#### Tests and tools

- tools/holo: gen3d.py runs on bromigOS's creation providers (bromigos art make model3d.generate) ([49fb85d](https://github.com/bromigos-org/vector-archive/commit/49fb85d5c1f5ad0cbd81725898398a6d75d9f423))

#### Packaging and CI

- packaging: channels: a version tag publishes bromigos-vector to stable (vX.Y.Z) or rc (-rcN); main stays edge ([cf333d4](https://github.com/bromigos-org/vector-archive/commit/cf333d47e6c213d80bebb61c12ff6d9040a6ee64))
