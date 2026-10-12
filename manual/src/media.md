# Your media

Find a show, film or album, download it to your own library, and watch it on your media
server or the desktop's den TV. You can use commands, the terminal's media library, or
VECTOR, the desktop's AI assistant.

Your [homelab](homelab.md#media-requests) needs the matching services connected first:
Sonarr for shows, Radarr for films and Lidarr for music. Seerr can handle requests too.
Pinchflat downloads YouTube. Jellyfin or Plex plays the files.

## Get a show, film or album

### From the Media app

Open `bromigos media`, then choose **Search** or press `7` or `Ctrl+F`.
Type a title, choose Films, TV, Anime or Music, and press Enter or the **Search** button.
Search includes media you do not have yet. The **Have it** column shows existing matches.
Press Enter on a result to choose what to request, its quality and audio languages.
Searching alone does not download anything. `/` filters titles already in your library.

![The Media app’s Search tab with a film outside the library](images/media-search.webp)

### From a terminal

Find the right title first:

```bash
bromigos lab media search "Cowboy Bebop" --anime
bromigos lab media search "Dune" --movie
bromigos lab media search "Daft Punk" --music
```

Each result has an ID, a year and a kind. Use that ID if several titles share a name.
For music, the results can be artists or individual albums. An artist request gets its
albums; an album request gets just that album.

To request a show, including its specials, at up to 1080p with English audio:

```bash
bromigos lab media get tv:tvdb:76885 --seasons all --specials --quality 1080p --audio en
bromigos lab media get "Dune" --movie --quality 1080p --audio en
bromigos lab media get "album:<musicbrainz-id>" --music
```

The command shows the title, quality profile, audio rule, estimated size and free space.
Read the plan, then confirm. It requests the download and keeps watching for missing
files. A quality profile is your server's rule for which releases it accepts.

For the album, replace `<musicbrainz-id>` with the album ID from search.
For another title, replace `tv:tvdb:76885` with the ID from search. You can also use a
name with `--tv`, `--movie`, `--anime` or `--music`.

- Pick seasons with `--seasons 1,3`, a range such as `--seasons 2-4`, or `--seasons latest`.
- Pick episodes with `--episodes S02E05,S02E06`.
- Use `--seasons future` to wait for new episodes without fetching old seasons.
- New episodes and seasons are monitored by default. Add `--new no` to stop that.
- `--quality best` uses the best profile your server offers. `2160p`, `1080p` and `720p`
  set a ceiling. Your server still needs a suitable profile.

For every option, see the [media command reference](https://github.com/bromigos-org/bromigOS/blob/main/docs/lab.md#media-requests).
`bromigos media get …` is another spelling of `bromigos lab media get …`.

### Choose your audio language

Audio rules apply to films and shows, including anime. To require English and favour a
second Japanese track when available:

```bash
bromigos lab media language set en ja
bromigos lab media language anime same
bromigos lab media language required yes
bromigos lab media language subtitles en
bromigos lab media language show
```

The first language is required. The others are welcome as extra tracks. Subtitles are a
separate choice. `--audio en` changes one request, while these commands save your defaults.
You can change them in **Settings › Lab** too.

Your server's profiles must enforce the rule. If they cannot, the request plan warns you.
Check that warning before confirming. The reference explains
[language profiles](https://github.com/bromigos-org/bromigOS/blob/main/docs/lab.md#media-requests).

### Track something that is not out yet

Search for the title and request its ID as usual. A film request uses `--when released`
by default: it waits for the home release. It does not ask for a cinema recording.
Shows can monitor future episodes with `--seasons future`.

The title appears in **Upcoming**, with the release dates your server knows. A title
with no date stays monitored; requesting it cannot make a release arrive sooner.

### Use the media library in the terminal

```bash
bromigos media
```

![The media library shows TV titles and their seasons in the terminal](images/media-library.webp)

Choose **Search**, or press `7` or `Ctrl+F`. Search, pick a result and choose its seasons, quality and
audio. The form previews the request automatically and updates it when you change
an option. Read the title, scope, quality and space estimate, then choose
**Request**. That button stays unavailable until the current preview is ready.
**Preview** reads the plan again.

After you confirm, **Requesting…** appears and the form waits for the result. Its
controls stay locked while your media service handles the request. A successful
request closes the form. An error stays visible in the form so you can review it.

The **TV**, **Movies** and **Music** tabs show what you have. Use arrows or `j`, `k`, `h`
and `l` to move. Pick a show to see its seasons, or an artist to see its albums. Press `P`
to change its profile, `m` to change monitoring, or `f` to search now.
On the top tabs, `Left`/`Right` or `h`/`l` selects the previous or next tab.
Press `Down` or `j` to enter the table. At its first row,
`Up` or `k` takes you back. Press `?` for keyboard help.
Press `Ctrl+C` to quit from the main screen. In a dialog, `Escape` or `Ctrl+C`
cancels an unconfirmed dialog and returns to the library. Letters such as `q` stay available
while typing. A dialog keeps the background tabs and actions inactive.
See the [library's keys](lab.md#your-media-library) for the full list.

### Ask VECTOR

Press `Super+E` and ask, for example:

- “Get season 2 of this show, up to 1080p, with English audio.”
- “Find this album and show me what you would download.”
- “Track this film and get it when the home release comes out.”

Give the title and year if there could be several matches. VECTOR tells you what he
found and the plan. He asks before requesting unless you clearly asked him to download
one title. You can also ask what is missing or when it will arrive.

## See what is downloading or coming up

```bash
bromigos lab media status
bromigos lab media status "Cowboy Bebop"
bromigos lab media upcoming --days 30
bromigos lab media recent --hours 24
```

`status` shows progress, time left and failures. A season pack’s size and speed are
counted once, even when it covers several episodes. Stalled torrents, paused
downloads and torrents waiting for their details are labelled separately from
active downloads. A stalled torrent with no connected seeders says so. A title's status adds its seasons,
monitoring, file languages and subtitles. `upcoming` lists what you track, with its
known dates. `recent` lists files that reached the library.

In `bromigos media`, use **Downloads** or **Upcoming**. You can also ask VECTOR,
“What's downloading?” or “What's coming up this month?”

## Delete safely

Pick the smallest thing you want to remove. To delete one season:

```bash
bromigos lab media delete "Cowboy Bebop" --season 1
```

It shows which files will go and how much space that frees. Type the title to confirm.
Deleting is permanent. Cancel if the scope or title is wrong.

Without `--season`, it deletes the whole title and its files. `--episodes` picks episode
files. For music, `--album` picks one album from an artist. `--exclude` keeps a whole
removed title or album from being added back by an import list. A removed season or
episode stops being monitored.

In the terminal library, select the title, season or album and press `D`. Read the
question, then choose **Delete** or **Cancel**. Cancel is selected first; `Escape` or `Ctrl+C` cancels. **Don't fetch it again**
adds the import exclusion. To keep files and only stop looking for more, use `m` instead.
The [delete reference](https://github.com/bromigos-org/bromigOS/blob/main/docs/lab.md#the-media-library)
explains the scopes.

The delete dialog starts on Cancel. `Left`/`Right` chooses a button and Enter
activates it. `Up`/`Down` moves to or from the exclusion checkbox; Enter or Space
toggles it. `Tab` and `Shift+Tab` also move between controls.
`Escape` or `Ctrl+C` cancels.

## Keep YouTube channels and playlists

To download new uploads from a channel into your library:

```bash
bromigos lab youtube add https://www.youtube.com/@NASAGoddard --since 2025-01-01 --quality 1080p
bromigos lab youtube list
bromigos lab youtube status
```

A playlist address works too. Pinchflat keeps its order. `--since` skips older uploads.
To pause a source, run `bromigos lab youtube pause "<source-name>"`. Replace
`<source-name>` with its name from `list`. `resume` starts it again, and `refresh` checks
for new videos now.

`bromigos lab youtube remove "<source-name>"` asks before removing a source. Its videos
stay on disk. Add `--delete-files` only when you want to remove the files too.

To make downloaded playlists appear in Jellyfin or Plex in YouTube's order:

```bash
bromigos lab youtube sync --dry-run
bromigos lab youtube sync
```

The first command previews changes. The second applies them. See
[YouTube downloads](lab.md#youtube-downloads) for quality, sign-in cookies and every
command, and [connection settings](homelab.md#youtube-downloads-with-pinchflat).

## Watch on the den TV

The den is the default theme's wallpaper: a radio room with three live screens. Each
screen can play a different channel from your library, YouTube or a folder of videos.

1. Open the guide with `Super+Alt+G`, **GUIDE** in a screen's hover controls, or
   **Settings › Den TV**.
2. Choose **Add channel…**, then **Shows or movies you pick**. Search your library and
   select the posters you want. Pick the order and give the channel a name.
3. Choose **BIG**, **SCOPE** or **SMALL** on its card to put that screen on the channel.
4. Click a playing screen, or **FULL**, to watch full screen with sound. Close the player
   to return to the desktop.

For a **Night Block**, make a channel with that name and pick the shows for your evening.
Choose **in order** or **shuffle**. Turn on **Bumpers** in its menu for short cards between
items. This is a channel you make, not a preset schedule.

The screens start silent. Turn sound on with the speaker in a screen's controls. Only
one screen has sound at a time. Channel 1 restores that screen's normal picture.
For all controls and channel settings, see [The den TV](themes-and-worlds.md#the-den-tv).

## Make channels for the den TV

In `bromigos media`, choose **Channels** or press `8`. Each channel shows its kind,
play order, bumpers and the screens on it now. Select one to see its titles and what's
on now and next. A library channel includes everything in its library. A picked channel
holds the shows, movies, YouTube addresses or music you choose.

From **TV**, **Movies**, **YouTube** or **Music**, select a title and click
**Add to channel… (c)** below the list, or press `c`. This also works on Search
results, Downloads and Upcoming titles. In Music, selecting an album adds that album.
Choose **Add to Night Block** (or another picked channel), then **Apply channel choice**.
You can also choose **Remove from…** or **New channel…**.

![The Media channel picker with Add to Night Block selected](images/media-channel-picker.webp)

A small diamond marks titles already in a channel. Select or hover over a title to
see its channel names. The names also stay visible beside **Add to channel…**.
The picker lists its current channels and marks **Already in … — remove**.

![A selected show marked with a diamond and the channel names Night Block and Weekend](images/media-channel-membership.webp)

Adding something to a channel does not download it; it must be
available from the media server or YouTube. Music plays through the den's sound controls.

On **Channels**, `Ctrl+N` adds a channel, `F2` renames it, `v` changes its order, and `b`
switches bumpers. Select a picked item and use `Alt+Up` or `Alt+Down` to reorder it,
or `x` to remove it. From the channel list, the same arrows move the whole channel.
`D` asks before deleting a channel. `Ctrl+Z` restores the last deleted channel.
**Tune**, or `c` on this tab, chooses a screen.

Removing a pick or a channel keeps the media files. Each change shows a confirmation
message, preserves comments in the config, and reaches the den without a restart.
The [Den TV app](themes-and-worlds.md#the-channel-guide) offers the same channels in a
window with posters.

### Use commands or ask VECTOR

To see the channels and add a show:

```bash
bromigos-live tv channels --json
bromigos-live tv channel add "Night Block" --shows "Example Show" "Another Show" --order alternate --bumpers
bromigos lab media channel add "Example Show" --to "Night Block" --json
```

Names work wherever a command asks for a channel. The numbers in `tv channels` are
positions in the config. Screen numbers are separate: channel 1 is each screen's own
picture. `channel tune` finds the right screen number from the name.

```bash
bromigos-live tv channel add-item "Night Block" "Example Film" --kind movie --json
bromigos-live tv channel remove-item "Night Block" "Example Show" --json
bromigos-live tv channel move-item "Night Block" "Another Show" 1 --json
bromigos-live tv channel order "Night Block" shuffle --json
bromigos-live tv channel bumpers "Night Block" off --json
bromigos-live tv channel rename "Night Block" "Evening" --json
bromigos-live tv channel move "Evening" 1 --json
bromigos-live tv channel tune "Evening" --screen wave --json
bromigos-live tv channel remove "Evening"
bromigos-live tv channel undo --json
```

`remove` asks you to type the channel name. Scripts can pass `--yes`. All channel
commands accept `--json`. Exit codes are 0 for success, 1 for an operation that failed,
2 for invalid arguments or a missing confirmation, 3 for a conflicting name, and 4 for
something not found. `tv channels --refresh` reads library contents from the servers;
without it, now/next and contents use the local cache.

Ask VECTOR, the desktop's AI assistant, "Add this show to Night Block", "What's on the
den TV?", or "Tune the scope to Evening". From the phone he can read channels and add
or remove individual picks. Creating channels, tuning screens and deleting whole
channels stay on the desktop. A whole-channel delete needs your explicit request naming
it. The [command reference](commands.md) and `bromigos-live tv channel --help` list the
options for libraries, YouTube and folders.

## Put releases on your calendar

Open the CALENDAR panel's **Settings…** and turn on **Your media server's releases**.
It adds tracked TV episodes and film releases from Sonarr and Radarr to your other events.
It needs those services connected through [Your homelab](homelab.md#media-requests).

You can show the panel from **Customize › Widgets**, or run:

```bash
bromigos panels show calendars
```

See [Calendar releases](panels.md#calendar-releases) for the setting and feed export.

## If something goes wrong

### Nothing was found or nothing is downloading

Search with the kind and year. If the name is ambiguous, use the result's ID. A title can
exist in the catalogue before there is anything to download.

For a tracked title, ask the indexers now:

```bash
bromigos lab media status "Cowboy Bebop" --why
bromigos lab doctor
```

The first command explains missing releases and rejections. The doctor checks whether
the connected services answer. A release can be rejected for quality, language or a
profile's minimum score. Check those rules before relaxing them.

### The audio is in the wrong language

Use `language show` and the title's `status` to compare your request with the files.
Check the selected profile in Sonarr or Radarr. Changing the defaults does not rewrite
files you already downloaded. Pick the right profile and search again; keep the old
files until you have checked the replacement.

### Jellyfin cannot play a file

Check that Jellyfin can see the media folder, and that its container has the right
permissions. Check the media server's logs for missing files or transcoding errors.

If several media apps freeze while the NAS still answers, its client may have a stuck
NFS lock connection. Ask the lab administrator to check it through the lab's maintenance
procedure. See [Media files on a NAS](troubleshooting.md#media-files-on-a-nas).

## Play something on a den screen

Press `p` in the media library to open **Play on den TV**. Choose BIG, SCOPE or SMALL.
Pick a show, then its season and episode, or choose a movie. The YouTube view lists
downloaded videos; you can also search with a YouTube video URL. Turn **Resume where
you left off** on to use the server's saved position. Otherwise playback starts at the
beginning. `P` changes a quality profile.

The Den TV app has a **Play…** button for each screen with the same choices.
The screen shows **ON DEMAND** while your choice plays. When it ends, or you change
channel, the screen returns to its channel's live schedule.

```bash
bromigos-live tv play --screen big "Cowboy Bebop S01E05" --json
bromigos-live tv play --screen scope --id ITEM_ID --source SERVER_NAME --resume --json
bromigos-live tv play --screen small --url "https://www.youtube.com/watch?v=VIDEO_ID" --json
bromigos-live tv search "Cowboy Bebop" --kind shows --json
```

`SERVER_NAME` is a source name from your media settings. Use `--id` when titles are
ambiguous. Search with `--kind seasons --id SHOW_ID`, then `--kind episodes --id SHOW_ID
--season 1` to list episodes. Ask VECTOR to “play Cowboy Bebop episode 5 on the big TV.”
See [the den controls](themes-and-worlds.md#the-den-tv) for sound, full screen and the
number-pad remote.
