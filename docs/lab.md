# The lab console: bromigos lab

`bromigos lab` is your homelab's front door on the desktop. It shows what the lab is
doing, what its GPUs hold and what needs fixing, and it queues work on the lab's GPUs.
This page explains how it works, for someone extending it or debugging it. For using it,
read the manual's [The lab console](../manual/src/lab.md) page.

The console ships as standalone `bromigos-lab`. The desktop integration package
`bromigos-homelab` depends on it and reads the same sources as the rest of the
desktop ([homelab.md](homelab.md)). A *source* is one of your services, listed in
`homelab.toml`. Whatever your lab lacks is simply absent. A source that doesn't answer
shows *unreachable*, and nothing crashes.

## Everything it does

| Command or key | What it does |
|---|---|
| `bromigos lab` | Open the live dashboard in a terminal. |
| `bromigos lab status [--json] [--card ID]` | Show one card per part of the lab. |
| `bromigos lab models` | Show what's installed and loaded where, with VRAM. Load and unload models. |
| `bromigos lab models recommend`, `plan`, `upgrades` | Ask the model catalog ([lab-models.md](lab-models.md)). |
| `bromigos lab run KIND [PRESET] …` | Queue a job on the lab's GPUs. |
| `bromigos lab jobs` | List, follow, cancel and retry jobs. |
| `bromigos lab doctor [--json]` | Run checks. Each problem comes with a fix in plain words. |
| `bromigos lab youtube` | Show Pinchflat's YouTube downloads card ([below](#youtube-downloads)). |
| `bromigos lab youtube add`, `list`, `remove`, `pause`, `resume`, `refresh`, `status`, `quality`, `cookies` | Control Pinchflat without its web page ([below](#youtube-downloads)). |
| `bromigos lab youtube sync` | Turn Pinchflat's playlists into playlists in Jellyfin and Plex. |
| `bromigos lab media search`, `get`, `status`, `upcoming`, `recent`, `language` | Ask your media stack for films, shows, anime and music at the best quality, in your languages ([below](#media-requests)). |
| `bromigos media` | Your media library in a terminal: browse, monitor, change quality, play, delete ([below](#media-requests)). |
| `bromigos lab provision …` | Generate and apply Core or Advanced on your own target ([lab-provision.md](lab-provision.md)). |
| `bromigos lab connect …` | Run `bromigos setup homelab …`: find services and write `homelab.toml`. |
| `bromigos lab target …` | Run `bromigos target …`: choose where AI runs ([targets.md](targets.md)). |
| Super+Shift+H | Open the Lab deck, a hologram of the rack lit by the same readings. |
| Settings › Lab | See the status, models, recent jobs, the doctor and the targets in a window. Set your media languages. |

> **Planned.** Changing the lab itself is Phase 2: deploying, restarting, logs, backups,
> power, and adding or replacing models. Those commands only say they are not built yet.
> Setting up Core and Advanced is built in `lab provision`
> ([lab-provision.md](lab-provision.md)). See [Planned: changing the lab](#planned-changing-the-lab).

## The dashboard

`bromigos lab` with no arguments opens a terminal dashboard built with Textual. It has five
tabs: STATUS, MODELS, JOBS, DOCTOR and PROVISION. It reads the lab again every 15 seconds. When the
output isn't a terminal, it prints the status instead.

| Key | What it does |
|---|---|
| 1, 2, 3, 4 | Switch to Status, Models, Jobs or Doctor. |
| r | Read the lab again now. |
| n | Queue a new job. |
| c | Cancel the job under the cursor. |
| R | Retry the job under the cursor. |
| d | Run the doctor now. |
| q | Quit. |
| ↓ ↑, j k | Move through the cards (each shows as you reach it) or a table's rows. |
| → ←, l h | On Status, move between the cards and the detail table. |
| g, G | The first or last item. |
| Ctrl+D, Ctrl+U | A page down or up in a table. |
| ], [ or L, H | The next or previous tab. Switching tabs puts the keyboard on that tab's list. |

The dashboard needs `python-textual`. Without it, `bromigos lab` says so and prints the
status.

## Status

`bromigos lab status` asks every source at once. It prints one line per *card*. Cards that
need attention also list their items.

| Card | What it shows | From |
|---|---|---|
| Nodes | each machine: up, CPU, memory, root disk and load | `hosts` |
| GPUs | each GPU: VRAM used of total, busy %, temperature, power, and what uses it | `gpus`, else NVIDIA's DCGM exporter, else the media server |
| Services | ComfyUI, the voice service and each model server | `media`, `voice`, `models` |
| Models | the models the servers serve, with requests a minute and tokens a second | `models` |
| GitOps apps | Argo CD or Flux apps, with sync and health, problems first | `deployments` |
| Workloads | how many pods, containers and VMs run, and the ones that don't | `workloads` |
| Storage | each NAS share the lab uses, with its NAS and its free space; the NAS's pools; then every root disk; fullest first | `storage`, NFS and SMB mounts, `hosts` |
| YouTube downloads | Pinchflat: its download queue and failed jobs, then each channel and playlist with its newest video | `youtube-downloader` |
| Alerts | firing and pending alerts | `alerts` |
| Jobs | the lab's job queue | the queue's state |
| Vault | up or sealed, never a secret | `secrets` |
| others | every other capability a source provides gets a card of its own | the registry |

A few details:

- **Nodes** has one row per host, whichever sources know about it. Hosts come from
  node-exporter, Kubernetes, Proxmox, Netdata or a Lab API.
- **GPUs** lists every pod that asks for each GPU. A machine with unified memory, such as
  a DGX Spark, shows its memory as its node's. A model served across two GPUs is named on
  both.
- **Alerts** leaves out Prometheus's always-firing Watchdog alert.
- **YouTube downloads** has a hover hint on every row. Pinchflat's row lists the newest
  downloads. A playlist's row says that `bromigos lab youtube sync` turns it into a
  playlist on your media server. In the dashboard, the card has an **Add a channel or
  playlist…** button (key `a`), a form that runs the same code as `bromigos lab youtube
  add`.

Each card is `ok`, `warn`, `crit`, `unreachable` or `empty`. The console's own state is
its worst card's.

- `--card gpus` prints one card in full.
- `--json` prints the document every other view reads: the dashboard, the deck, Settings
  and VECTOR.
- `[console] hide = ["pattern", …]` in `homelab.toml` keeps items off every card, such as
  an internal app you don't want in a screenshot.

To add a card, see [Status cards](homelab.md#status-cards).

### YouTube downloads

[Pinchflat](homelab.md#youtube-downloads-pinchflat) downloads YouTube channels and
playlists into your media library. `bromigos lab youtube` shows its card in full. The other
commands control it. The manual's [Lab console](../manual/src/lab.md#youtube-downloads)
page shows how to use them.

| Command | What it does in Pinchflat |
|---|---|
| `add URL [--playlist\|--channel] [--since DATE] [--name NAME] [--quality Q]` | Creates a source. The URL says playlist or channel. A playlist gets the `Playlists (in order)` media profile, a channel `Channels (Media Center)`. |
| `list` | Every source: kind, quality, videos downloaded and waiting, last check, newest video. |
| `remove NAME\|URL [--delete-files] [--yes]` | Deletes the source after asking. The files stay unless `--delete-files`. |
| `pause NAME`, `resume NAME` | Turns the source's Enabled switch off or on. |
| `refresh [NAME]` | Force Index on one source, or on all. |
| `status` | The download queue and failed jobs (its metrics), active tasks, recent downloads. |
| `quality NAME Q` | Moves the source to the profile for that quality. New downloads only. |
| `cookies set FILE \| clear \| status` | Stores YouTube cookies, and turns Cookie Behaviour to When Needed on every source (or off). |

Each one takes `--json`. The code is `homelab/lib/bromigos_homelab/pinchflat.py`.

**How it talks to Pinchflat.** Pinchflat has no JSON API. It's a Phoenix app, so the code
drives its web pages the way a browser does:

1. It GETs the page with the form, such as `/sources/new`, with the basic auth.
2. It keeps the session cookie and reads the CSRF token from the page.
3. It POSTs the form back. A new source sends every field the form has, with Pinchflat's
   own defaults. An edit sends only the field it changes, with `_method=patch`.

Pinchflat answers a good form with a redirect. It answers a bad one with the form again,
and the command prints the form's errors. Delete, Force Index and the Enabled switch are
links and toggles in its pages. The code POSTs what those send.

It was built against Pinchflat v2025.9.26. Before it sends a form, it checks that the form
has every field it needs. If one is missing, Pinchflat has changed: the command stops,
sends nothing, and says so.

It lists sources through the media profiles' pages, because the Sources page shows ten at
a time and only to a browser. Each source's own page has its settings and its counts.

**Quality.** Pinchflat sets quality per media profile. Its choices are `4320p`, `2160p`,
`1440p`, `1080p`, `720p`, `480p`, `360p` and `audio`. `best` means `4320p`, its highest:
yt-dlp then takes the best a video has. For a quality other than the base profile's, the
code makes a copy of the base profile at that quality, named like `Playlists (in order) ·
2160p`. It makes it through Pinchflat's own "use as template" form, so every other setting,
the output template included, is the base's. It reuses the copy next time. A lab that
keeps the base profiles' templates in step should keep the copies' too.

**Configuration.** It reads the first `pinchflat` source in `homelab.toml`, or the one
`--source NAME` names:

```toml
[[source]]
name = "pinchflat"
type = "pinchflat"
endpoint = "https://pinchflat.lab.example"
auth_ref = "@file:~/.local/share/bromigos/pinchflat-login"   # "user:password"
# or: user_ref = "@file:…/pinchflat-user", and auth_ref holds only the password
cookies_store = "vault:secret/lab/pinchflat#cookies"   # or "file:/path/to/extras/cookies.txt"

[youtube]
quality = "1080p"                                 # the default for add
channel_profile = "Channels (Media Center)"      # the profile a channel gets
playlist_profile = "Playlists (in order)"        # and a playlist
```

When neither profile name exists and Pinchflat has only one profile, that one is used.
`PINCHFLAT_URL` and `PINCHFLAT_AUTH` replace the endpoint and the login.

**Cookies.** `cookies set` checks that the file is a Netscape `cookies.txt` with
youtube.com cookies. It never prints a value. Then it writes the file to the store:

- `vault:PATH#FIELD` writes the field, and `FIELD_set_at` beside it, with the `vault` CLI
  and its login. The rest of the path is kept. `clear` empties the field rather than
  deleting it. A lab that copies the field into Pinchflat's `extras/cookies.txt`, for
  example with an ExternalSecret, gets the change at its next refresh.
- `file:PATH` writes the file itself, mode 0600.

`cookies status` reads the store and warns when the cookies are over 30 days old.

**Sizes.** The manual's table of disk space per hour comes from yt-dlp's format lists for
35 recent NASA videos, read in October 2026 with Pinchflat's own format choice (H.264 up to
1080p, VP9 above it). The medians were about 1.1 GB an hour at 1080p and 5.8 GB at 4K. The
highest were 2 GB and 9 GB, for 60-frames-a-second video.

**Tests.** `homelab/tests/test_lab_youtube_cli.py` runs every command against a fake
Pinchflat (`homelab/tests/pinchflatfake.py`). The fake serves pages recorded from a real
Pinchflat v2025.9.26 (`homelab/tests/fixtures/pinchflat/`), with the host and tokens
replaced. It checks the CSRF token and the session cookie as Phoenix does.

### Playlists in your media server

`bromigos lab youtube sync` turns each downloaded YouTube playlist into a playlist in
Jellyfin, Plex, or both, in the playlist's order. It's safe to run again. Add `--dry-run`
to see what it would change first.

### Media requests

`bromigos lab media` asks your lab's media stack for a film, a show, an anime or music, at
the best quality its profiles allow and in your languages. The manual's
[Lab console](../manual/src/lab.md#media-requests) page shows how to use it. The code is
`homelab/lib/bromigos_homelab/mediareq.py`, and the adapters it reads through are in
`adapters/labrequests.py` (Seerr, qBittorrent, SABnzbd, slskd) and `adapters/labmedia.py`
(the `arr` type, Jellyfin, Plex).

| Command | What it does |
|---|---|
| `search NAME [--movie\|--tv\|--anime\|--music]` | Titles with their year, kind, release dates, the profile each would get, the estimated size, and whether Jellyfin, Plex, Sonarr, Radarr or Seerr already has it |
| `get ID\|NAME\|URL [options] [--yes]` | Prints the plan, asks, then requests. Without a terminal it needs `--yes`, and exits 2 with the plan otherwise |
| `status [NAME] [--why]` | What's downloading, stuck, imported or failed, and why. With a name: that title's seasons, monitoring, audio and subtitles |
| `upcoming [--days N]` | What you track and when it comes out (Sonarr's and Radarr's calendars) |
| `recent [--hours N]` | What Sonarr, Radarr and Lidarr imported lately |
| `language [show\|set\|anime\|subtitles\|required] …` | Your languages: `[media]` in `homelab.toml` |
| `calendar tv\|movies` | Sonarr's or Radarr's iCal feed, for the Calendar widget |

Each takes `--json`. `bromigos lab media` alone shows the Requests card. Exit codes: 0 done,
1 an error, 2 asked and not confirmed, 3 the name matches several titles (the JSON lists
them), 4 nothing found.

`get`'s options:

| Option | Meaning |
|---|---|
| `--quality best\|2160p\|1080p\|720p` | best (the default), or a ceiling: a profile that allows more is skipped |
| `--audio en\|ja\|any` | This request's audio, instead of your setting |
| `--seasons all\|latest\|future\|none\|1,3\|2-4` | What to fetch now. `future` fetches nothing now and only new episodes from here on |
| `--episodes S02E05,S03E01` | Just these episodes |
| `--specials` | Season 0 too |
| `--new yes\|no` | Pick up new episodes and seasons (Sonarr's `monitorNewItems`). Default yes |
| `--when announced\|cinemas\|released` | Films: Radarr's minimum availability. Default `released`, the home release, so never a cam copy |

**Where a request goes.**

- **TV and films** go through Seerr when a `seerr` source exists and has a non-4K server.
  The request carries the profile, the root folder and the seasons, so it shows in Seerr.
  Afterwards the code sets what Seerr can't in Sonarr: the anime series type, specials, and
  new-item monitoring. `future`, `none` and `--episodes` go straight to Sonarr.
- **A show already in Sonarr** never goes through Seerr. Its monitoring changes in Sonarr:
  the seasons asked for are added to what's monitored, so "also get season 4" leaves 1–3 as
  they were. Its profile changes only with `--quality` or `--audio`.
- **Monitoring** uses Sonarr's own operations. `all`, `latest` and `future` are its season
  pass monitor options. Season numbers set each season's monitored flag, and the episodes
  follow it. Episodes use `episode/monitor`. Then it searches what's wanted now.
- **Music** goes to Lidarr: an artist with all its albums, or one album (its artist is added
  unmonitored). When Lidarr's album search finishes with nothing in its queue, slskd searches
  Soulseek. It picks the folder that's complete (80% of the album's tracks or more), then
  lossless, a free upload slot, a short queue and speed. The download is recorded in
  `~/.local/state/bromigos/media-requests.json`. When slskd has it, the next `status` asks
  Lidarr to import that folder (`DownloadedAlbumsScan` on the slskd source's `import_path`).
  Lidarr then moves it into the music library, where a music server such as Navidrome reads
  it.
- **A YouTube link** goes to Pinchflat, through the same code as `bromigos lab youtube add`.

**The profile.** `pick_profile()` reads the profiles that exist and their custom-format
scores. It never goes by a profile's name alone.

1. Anime goes to the anime profiles: a name with "Anime", or anime custom formats with
   scores. Other titles avoid them. A Recyclarr (TRaSH) profile, one with custom-format
   scores, beats a built-in one.
2. The audio rule decides among those (below).
3. Then the best quality it allows: resolution first, then remux, Blu-ray, web and TV.
4. Music takes the profile whose best is lossless, preferring one with nothing lossy.

It says which profile and why ("Remux + WEB 2160p: the best profile here, up to
Remux-2160p, a TRaSH profile; English audio required"). When nothing fits, it says that
too, for example "no anime profile here".

**Anime** is TMDB's anime keyword (Seerr's own test), TVDB's Anime genre or Sonarr's series
type, or animation whose original language is Japanese. Western animation isn't anime.

**Languages.** `[media]` in `homelab.toml` holds them, and `language` writes them. It edits
the `[media]` table in place, through a symlink if there is one, keeping comments. It
checks that the new file reads back before it replaces the old one.

```toml
[media]
audio = ["en", "ja"]       # best first, ISO 639-1; default: the desktop's language
audio_required = true      # the first must be there (default); false: only preferred
anime_audio = ["en", "ja"] # anime's own (default: audio)
subtitles = ["en"]         # what Bazarr fetches (default: the first audio language)
quality = "best"
seerr = true               # false: straight to the *arr apps
```

How they map onto Sonarr's and Radarr's profiles. A release's score is the sum of the custom
formats it matches, and a release under the profile's minimum score is never grabbed.
`profile_audio()` reads these scores:

| Your first audio language | The profile it takes | What the profile's scores do |
|---|---|---|
| English, required | `Remux-1080p - Anime (English audio)` | "Anime Dual Audio" +5000 and "Dubs Only" +4000, and a minimum of 3000. TRaSH's other formats can't reach 3000 without them, so a release with no English track is rejected |
| English, preferred | `Remux-1080p - Anime (English preferred)` | The same scores, no such minimum |
| Japanese or the original | `Remux-1080p - Anime` | TRaSH as published: "Dubs Only" -10000 |
| any | the one without a language rule | |

Live-action profiles with "Language: Not English" at -10000 count as English-required. The
homelab repository's Recyclarr config makes these profiles (its docs/arr-stack-setup.md,
"Audio language"). A lab without them gets the closest match, and the plan says the
language doesn't match.

**Subtitles.** `language subtitles` and `get` make a Bazarr language profile for your
subtitle languages when there's none, and make it the default for new series and films.
`get` gives the requested title that profile. `status` reads Bazarr's subtitles and missing
subtitles per episode. It says when Bazarr has no subtitle providers turned on, because then
it finds none.

**Status.** It joins Sonarr's, Radarr's and Lidarr's queues with the download clients, by
download id (a torrent's hash, SABnzbd's `nzo_id`). The progress, speed and time left come
from qBittorrent and SABnzbd, because the *arr queues lag behind them. The audio languages
come from the release names while downloading, and from the files' media info once they're
imported. With a name, it adds that title's seasons, monitoring, files below the profile's
target, failed downloads and why, and Bazarr's subtitles. If something is monitored, missing
and not downloading, it asks Prowlarr's indexers for the title (read-only). It says which
indexers answered with results, which with nothing, and which Prowlarr has paused for
failing.

**Is it there already?** Jellyfin and Plex are searched by title and matched on their TMDB,
TVDB or IMDb ids. Jellyfin also gives the resolution, the seasons, the episodes and the
audio languages.

**Size and space.** The estimate is the runtime times the profile's best quality's size per
minute, from the app's quality definitions (Recyclarr sets TRaSH's). It uses the preferred
size, else the middle of the minimum and maximum, else twice the minimum. The free space is
the root folder's, as the app reports it.

**Configuration.** One source per app. Every one is optional:

```toml
[[source]]
name = "seerr"
type = "seerr"
endpoint = "https://seerr.lab.example"
auth_ref = "@file:~/.local/share/bromigos/seerr-key"

[[source]]
name = "sonarr"            # also radarr, lidarr, prowlarr, bazarr: the name says which app
type = "arr"               # (or app = "sonarr"; else it asks the app)
endpoint = "https://sonarr.lab.example"
auth_ref = "@file:~/.local/share/bromigos/sonarr-key"

[[source]]
name = "qbittorrent"
type = "qbittorrent"
endpoint = "https://qbittorrent.lab.example"
auth_ref = "@file:~/.local/share/bromigos/qbittorrent-key"   # a WebUI API key (5.2+); or
                                                            # user_ref + auth_ref the password
[[source]]
name = "sabnzbd"
type = "sabnzbd"
endpoint = "https://sabnzbd.lab.example"
auth_ref = "@file:~/.local/share/bromigos/sabnzbd-key"

[[source]]
name = "slskd"
type = "slskd"
endpoint = "https://slskd.lab.example"
auth_ref = "@file:~/.local/share/bromigos/slskd-password"   # user_ref: its user, "slskd" by default
import_path = "/media/downloads/slskd"                     # its downloads folder, as Lidarr sees it
```

Jellyfin, Plex and Pinchflat are the sources the console already reads.

**The media library, `bromigos media`.** A terminal UI (Textual,
`homelab/lib/bromigos_homelab/mediatui.py`) over the same functions. `bromigos media` is
`homelab/bin/bromigos-media`; `bromigos lab media` with nothing after it opens it too, in a
terminal. Without a terminal, both print the Requests card instead.

- Tabs: TV (Sonarr), MOVIES (Radarr), MUSIC (Lidarr), YOUTUBE (Pinchflat), DOWNLOADS,
  UPCOMING, ADD (search, then the `get` form) and CHANNELS (the den TV). The header has the library's totals and
  the free space.
- A title's side table lists its seasons, its albums, or a season's episode files (`e`).
- Keys act on the row under the cursor: `m` monitor, `n` new episodes, `p` profile, `f`
  search now, `o` and `O` open in Jellyfin and Seerr, `t` play (Jellyfin to mpv full
  screen, as the den TV opens a channel), `D` delete, `/` filter, `s` sort. Vim keys work
  beside the arrows, and every key, tab, row and button has a hint.
- `Ctrl+C` and `q` have priority over inputs and modal screens. Quitting dismisses an
  open confirmation with no result. Confirmed changes run synchronously to completion.
- `Down`/`j` enters the active tab's first table from the tab bar. `Up`/`k` at row zero
  returns to the tab bar. The tables share the lab's `HintTable` Vim bindings:
  `j`/`k`, `g`/`G`, `Ctrl+D`/`Ctrl+U`, and `h`/`l` or arrows between panes.
  `[`/`]` and `H`/`L` switch tabs even from an input. Switching tabs cancels an open dialog.
  A key strip above the footer shows the navigation keys.
- The lab console's `M` opens it, and returns to the console when it closes.

- Channels use `bromigos_tvchannels.Store`, shared with the standalone GTK guide and
  live CLI. `c` on a library title opens add/remove/new choices. A diamond marks channel
  membership. The Channels tab shows contents, order, bumpers, screens and now/next;
  its controls edit picks, reorder, tune, rename and confirm deletion, with undo.
  A cache-only poll updates screens and now/next every five seconds without cancelling
  slower content fetches. Reordering keeps the selected channel or pick.
  All channel tests use sandbox config and stub control sockets.

The same changes are CLI verbs too: `library`, `monitor`, `profile`, `refresh` and `delete`.

**Deleting.** `delete_plan()` says exactly what goes and how much space it frees. `delete()`
then does it:

- a whole title: the app's own delete, with `deleteFiles` and, when asked, an import
  exclusion. Its Seerr entry and requests go too;
- a season, episode files or an album: just those files. A season or those episodes then
  stop being monitored, so they aren't fetched again;
- then Jellyfin and Plex rescan.

The TUI asks twice: type the title, or press `D` again. The CLI asks you to type the title,
or takes `--yes`. VECTOR's `media_delete` deletes only when your latest words ask for it and
name the title. His terminal can't run `delete` at all.

**Tests.** `homelab/tests/test_lab_media.py` covers the profile picker, anime detection, the
languages, seasons and episodes, and every command. `homelab/tests/test_media_tui.py` drives
the TUI with Textual's pilot: every tab, the delete dialog (cancel, typing the name, `D`
twice, a season), quitting from every tab and modal, arrows and Vim keys between tabs
and content, monitor, profile, open, search and request, and filter and sort. With
`MEDIA_SCREENSHOTS=DIR` it writes each tab as an SVG; the manual's pictures come from those. It runs them against a fake stack
(`homelab/tests/mediafake.py`): one local server that answers like Seerr, Sonarr, Radarr,
Lidarr, Prowlarr, Bazarr, Jellyfin, Plex, qBittorrent, SABnzbd and slskd. It uses the apps'
recorded answer shapes, with made-up titles and values.

## Models

```bash
bromigos lab models                    # the GPUs, then each server: what's loaded, files on disk
bromigos lab models --all              # every model file ComfyUI has, by folder
bromigos lab models load NAME          # load an Ollama model
bromigos lab models unload NAME        # unload an Ollama model
bromigos lab models unload comfyui     # free what ComfyUI holds
```

`load` keeps an Ollama model loaded for 30 minutes after its last use. When a name is on
several servers, `--source` picks one.

Unloading goes through each server's own API. It never restarts anything:

- For ComfyUI, it calls `POST /free`. ComfyUI applies it between prompts, so a running job
  finishes first. This is the same call ComfyUI's idle-unload sidecar makes after a few
  quiet minutes.
- For Ollama, it sets `keep_alive` to zero.
- The voice service's models are never unloaded from here, because VECTOR speaks through
  them.
- A vLLM server serves its model for as long as it runs.

ComfyUI loads what a job needs by itself. Loading ahead of time buys little, because a
cold start reads from fast local storage.

For the catalog's `recommend`, `plan`, `pick`, `tiers`, `upgrades`, `refresh` and `check`,
see [lab-models.md](lab-models.md).

## Jobs

A *job* is a piece of work the lab's GPUs do for you, such as an image or a voice line.

```bash
bromigos lab run image --prompt "a lighthouse at dusk" --aspect 16:9
bromigos lab run image world-painting --prompt "Tidewell at low tide"
bromigos lab run image-edit --input pic.png --prompt "make the sky stormy" --mask m.png
bromigos lab run cutout --input pic.png
bromigos lab run 3d --input cutout.png
bromigos lab run upscale --input pic.png --scale 2
bromigos lab run hologram --prompt "a brass telescope"
bromigos lab run voice --text "The relays are lit."
bromigos lab run transcribe --input talk.m4a
bromigos lab run batch-llm --input prompts.txt
bromigos lab run creature-loop --input creature.png --prompt "a veilwing drifting, fins rippling"
```

To see what can run on your lab, and why something can't:

```bash
bromigos lab run --kinds
bromigos lab run --presets
```

To follow the queue:

```bash
bromigos lab jobs                 # newest first; --all for every job
bromigos lab jobs watch           # follow the queue until it settles
bromigos lab jobs logs ID         # one job's log
bromigos lab jobs cancel ID
bromigos lab jobs retry ID
```

### Job kinds

The VRAM column is the peak each job adds on its GPU. It was measured on a 32 GB card on
2026-10-08 and 2026-10-09.

| Kind | Runs on | Peak VRAM it adds |
|---|---|---|
| `image`, `image-edit` | ComfyUI with Qwen-Image 2.1, through `bromigos art make` | 15.1 GiB for a 1024-pixel still |
| `cutout` | ComfyUI with Lucida | 1.0 GiB for a 1536-pixel image |
| `3d` | ComfyUI with Pixal3D, shape only | 10.2 to 12.5 GiB |
| `hologram` | the three above, then VECTOR's bake into a hologram | its largest step |
| `voice` | the voice service | none: its models stay loaded |
| `transcribe` | the voice service's Whisper | none |
| `batch-llm` | the lab's LLM server, the homelab `llm` in targets.toml | none: the server holds its memory |
| `video` | ComfyUI with Wan 2.2 TI2V-5B, through `bromigos art make video.loop` | 17.4 GiB for a 5-second 720p loop |
| `upscale` | ComfyUI with SeedVR2 7B, through `bromigos art make` | 8.5 to 8.7 GiB for an image at 2x |

Some details:

- A `cutout` takes about 2 seconds. A `3d` job takes 35 to 57 seconds. If the concept was
  seen from above, the mesh is stood upright afterwards.
- An `upscale` job makes an image or a short clip twice as large by default. `--scale`
  sets the factor, up to 4. The factor is lowered when the result would be bigger than
  the workflow makes: 8.4 megapixels a frame, or 120 megapixel-frames for a whole clip.
  An image at 2x takes 12 to 16 seconds, and a 5-second loop about 39 seconds.
- A `hologram` job goes from concept to cutout to 3D mesh, then VECTOR's `make-holo.py`
  bakes it into `~/Pictures/bromigos/lab/hologram/<name>/`.
- `voice` uses `/v1/audio/speech`, or `/v1/tts/stream` with a stored voice (`--voice ID`).
- `transcribe` uses `/v1/stt`. ffmpeg converts the audio first.
- A `video` job makes a seamless loop from a still in about 146 seconds. With
  `--alpha luma`, it's matted for a world.
- With an `ocr` source, there's also an `ocr` kind ([homelab.md](homelab.md#the-ocr-job-kind)).
- With the catalog's bench turned on, there's also `catalog-bench`
  ([lab-models.md](lab-models.md#measured-on-your-lab)).

### Presets

A *preset* is a job kind with ready-made options. Name it after its kind, as in
`bromigos lab run image world-painting`, or on its own, as in
`bromigos lab run creature-loop`.

| Preset | Kind | What it makes |
|---|---|---|
| `world-painting` | `image` | a wide 16:9 painted scene at 2048 pixels, for a world's background |
| `hologram` | `hologram` | a new hologram of a subject, made and baked on the lab |
| `voice-line` | `voice` | one short line in the voice service's default voice |
| `creature-loop` | `video` | a creature on black as a matted 5-second loop, for a world's live layer |

Measured numbers that jobs share live in `homelab/share/lab/jobs.toml`
([homelab.md](homelab.md#measured-kinds-jobstoml)).

### The queue

The queue is a user service, `bromigos-lab.service`, which runs `bromigos lab serve`.
`bromigos lab run` starts it when it isn't running. To keep it running:

```bash
systemctl --user enable --now bromigos-lab.service
```

Its state lives in `~/.local/state/bromigos/lab/`: a JSON file and a log per job.

**Heavy jobs** are the GPU kinds. They run one at a time, in the order they came. One
starts only when its GPU has room:

- the free VRAM, plus what an idle ComfyUI holds and would give back, must cover the
  kind's peak;
- on top of that, `[lab] voice_reserve_mib` stays free for the voice service, 1024 MiB by
  default;
- while ComfyUI is busy with someone else's prompts, the job waits.

A waiting job says why, for example: `waiting for VRAM: needs 15.1 GiB, 12.0 GiB can be
had, 1.0 GiB stays free for the voice service`. A job that could never fit fails at once.

ComfyUI doesn't report all the VRAM its loaded models use. So when a heavy job is short
of VRAM and ComfyUI is idle, the queue asks ComfyUI to unload its models (`POST /free`),
at most once every two minutes. The job then starts within seconds, instead of waiting
for the idle-unload sidecar.

**Light jobs** are voice lines, transcriptions and LLM batches. They run beside the heavy
ones, one at a time per backend, so a long batch never crowds the voice service.

The queue measures each heavy job: the most free VRAM its GPU lost while it ran. It keeps
the largest per kind in `vram.json`. The gate uses the larger of that and the kind's
measured number.

The queue never stops, restarts or reconfigures anything on the lab.

Results land in `~/Pictures/bromigos/lab/<kind>/`, and a notification says when a job
finishes or fails. Cancelling a running image job also removes its prompt from ComfyUI.

**Homelab first.** No job uses a paid provider unless you pass `--cloud` for that job.

## The doctor

`bromigos lab doctor` runs every check in parallel and prints what's wrong, each with a
fix. It only reads.

| Option | What it does |
|---|---|
| `--all` | Show the checks that passed too. |
| `--check ID` | Run one check. |
| `--json` | Print the findings as JSON. |

| Check | What it looks at |
|---|---|
| `sources` | every source answers for every capability it provides |
| `dns` | each source's host name resolves here |
| `tls` | each HTTPS source's certificate is trusted here: amber under 21 days left, red under 7 |
| `gpu` | the driver sees each GPU, and the media server sees CUDA |
| `disk` | root disks, NFS and SMB shares, and storage pools: amber from 85% full, red from 95% |
| `backups` | the last good backup of each `backups` source |
| `argo` | GitOps apps out of sync, or degraded |
| `tokens` | your Vault login's expiry, and each `[console] tokens` entry's `expires` metadata |
| `targets` | `targets.toml` points at services that answer |
| an adapter's own | anything a source checks about itself, such as certificates, the NAS or dynamic DNS |

The `tokens` check reads Vault *metadata* only, never a secret's value. An entry looks like
`[console] tokens = [{ name = "…", vault = "kv/path" }]`, with an `expires` date in the
secret's custom metadata.

To add a check, see [Doctor checks](homelab.md#doctor-checks).

## The Lab deck

A *deck* is a full-screen holographic view drawn by the live layer, the program that
draws bromigOS's animated background. The Lab deck is the console as a hologram. Open it
with **Super+Shift+H**, from the menu's HOLOGRAMS group, or with `bromigos-live lab`.

```bash
bromigos-live lab                 # toggle it, as the key does
bromigos-live lab open
bromigos-live lab close
bromigos-live lab focus gpus      # drill into a card or a node
bromigos-live lab clear
```

A hologram of a server rack stands in the middle. Its parts light up from the console's
cards:

| Part | Lit by |
|---|---|
| SWITCH | the services: red when one is down |
| NODES | the nodes: red when one is down or its disk is nearly full |
| GPU SERVER | the GPUs: amber when hot, pulsing while one works |
| STORAGE | disks and NAS shares, fullest first |
| POWER | what the GPUs draw |
| FRAME | GitOps apps and firing alerts |

The nodes orbit the rack. Each GPU node has a ring for its VRAM, which spins while the GPU
works, with the pods using it named underneath. Two GPUs serving one model together are
joined by a beam.

Along the bottom are dials and the job queue. The dials show nodes up, the biggest GPU's
VRAM, healthy GitOps apps, the fullest disk and firing alerts. The queue shows the media
GPU's VRAM, split into what others hold, what ComfyUI holds, what's kept for the voice
service and what's free, and then the jobs.

Hover anything for what it is. Click a rack part, a node, a dial or a card on the right
to list its items, as `--card` prints them. Backspace goes back.

The deck reads the cards every 10 seconds and the queue every 2 seconds, only while it's
open. Without VECTOR's hologram renderer, the rack is a wireframe, lit the same way. Under
reduced motion, nothing pulses or spins.

## Settings › Lab

The Lab page in Settings shows the same things in a window: the status, the GPUs and
models, the model planner, recent jobs with their results, the doctor's findings and where
AI runs. It reads `bromigos lab … --json` in the background, so the window never blocks.
From there you can free what ComfyUI holds. It doesn't change the lab otherwise.

## VECTOR and the lab

VECTOR reads the console and makes things on the lab through the same queue. His tools
are `lab_console`, `lab_jobs`, `lab_job_submit` and `lab_job_cancel`, in the vector
repository's `holo/vector/lab.py`. His media tools (`media_search`, `media_get`,
`media_status`, `media_upcoming`, `media_recent`, `media_language`, in
`holo/vector/media.py`) run `bromigos lab media`. He plans a request, tells you, and requests
on your go-ahead. His terminal may read `bromigos lab media`, but requests go through his
tools.

- His jobs are recorded as his.
- He never uses `--cloud`.
- He cancels only his own jobs.
- His terminal may read `bromigos lab`. It refuses anything that changes the lab or where
  AI runs: target switches, `connect`, model load and unload, and every Phase 2 verb.
- The queue's state folder is read-only to him.

## Extending the console

A `homelab-adapter` extension, or a file in `~/.config/bromigos/plugins/homelab/`, can add
cards, doctor checks and job kinds. It uses the same calls bromigOS does
([homelab.md](homelab.md#the-lab-console-cards-doctor-checks-and-job-kinds)). For example:

```python
# my_ups.py, part of a homelab-adapter extension
from bromigos_homelab import Adapter, register, console, doctor, jobs

@register
class Ups(Adapter):
    type = "nut"
    provides = ()
    default_ports = (3493,)

    def cards(self):                         # a card of its own
        return [{"title": "UPS", "summary": "on mains · 82 %", "items": [...]}]

    def doctor(self):                        # a check about itself
        return [doctor.finding("ups.battery", "UPS battery", "warn", "62 %",
                               "Replace the battery soon.")]

jobs.register_kind(jobs.Kind("ocr", "OCR", "text from a scan", run=run_ocr, needs=("ocr",),
                             takes=("input",), ext=".txt"))
```

Then:

1. Install it with `bromigos ext install <git url>`. It asks first, because it runs code.
2. Add a `[[source]]` of its type to `homelab.toml`.

It now appears on the console, in the doctor and in `bromigos lab run --kinds`.

## Planned: changing the lab

> **Planned.** These commands exist, but they only say they aren't built yet. The design
> is in [PLAN.md](PLAN.md).

Phase 2 will change the lab through your homelab's Git repository, never by hand on a
server. Every change will be a commit or a pull request that Argo CD, Flux or Ansible
applies, and each command will ask you first.

| Command | What it will do |
|---|---|
| `lab deploy <app> [--set k=v]` | Write the change in the repository, commit and push, then follow the sync and the rollout. `--pr` opens a pull request instead. |
| `lab logs <app>` | Show an app's logs from Loki, or else from the cluster. |
| `lab restart <app>` | Restart a Kubernetes rollout, through the repository or the API. |
| `lab backups` | List, run and restore backups. A restore will show what it overwrites. |
| `lab power` | Wake a sleeping machine, and set GPU power limits. |
| `lab models add`, `remove`, `replace` | Change the model set in ComfyUI's or vLLM's values. |

`lab provision` has its first slice built ([lab-provision.md](lab-provision.md)).
`lab update` remains planned.

## Tests

The unit tests run against answers recorded from a real lab and scrubbed
(`homelab/tests/fixtures/lab.json`, `labfake.py`):

- `test_lab_console.py`, `test_lab_doctor.py` and `test_lab_queue.py` cover the cards, the
  checks and the queue. That includes generic cards, unreachable sources, Vault read for
  metadata only, the VRAM gate with the voice reserve, heavy jobs in order, light jobs not
  blocked, cancel, retry, recovery, measured peaks and notifications.
- `test_lab_tui.py` drives the dashboard with Textual's pilot. It compares the first
  screen with `tests/snapshots/lab-tui.svg`, on the Textual version it was made with.

To render the deck and the Settings page offscreen:

```bash
live/tools/offscreen.py lab OUT.png 5
tools/settings/render.sh OUT --page lab --path DIR
```

For the Settings page, `--path` is a folder with a `bromigos-lab` that answers from
recorded JSON.

`homelab/tests/e2e_lab.py` runs against a real lab, under `dbus-run-session`. It reads the
lab, then sends one voice line and one image through the queue. It checks their
notifications on the private bus, and that what the image loaded is unloaded again.

The last run, on 2026-10-09 against a real homelab:

- the status: 12 cards in 12.4 seconds;
- the doctor: 35 checks passed and 2 to look at, in 15.8 seconds;
- a 4.6-second voice line, made in 2 seconds;
- a 1024-pixel image in 17 seconds, for no credits, peaking at 15.1 GiB of VRAM;
- both notifications, and ComfyUI back to 64 MiB after the unload.

## VM and cluster provisioning

The Provision tab can review a generated repository, plan a cluster specification,
apply a plan, add a node, drain a worker or run an owned VM command. Resource changes run in the terminal and
keep their explicit approval prompts. Capacity and VM cards use read-only adapter data.
[Infrastructure](lab-infrastructure.md) describes providers, storage and monitoring.

The [standalone package](lab-package.md) runs without desktop dependencies and publishes
to the AUR after a clean Arch install test.
