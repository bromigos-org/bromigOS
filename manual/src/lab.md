# The lab console

`bromigos lab` is the console for [your homelab](homelab.md). It shows what the lab is
doing and what its graphics cards hold, runs AI jobs on them, and checks the lab for
problems. It reads the services you connected. Anything your lab doesn't have is simply
not shown.

You need a homelab connected first: run `bromigos setup homelab`.

## Look at your lab

Run `bromigos lab` for the live dashboard. It refreshes every 15 seconds.

![The lab console's Status tab: a card for each part of the lab, and the machines in detail](images/lab-console.webp)

| Key | What it does |
|---|---|
| <kbd>1</kbd> | Status: a card for each part of the lab, such as machines, graphics cards, services, storage and alerts. |
| <kbd>2</kbd> | Models: the AI models each machine holds, and their memory. |
| <kbd>3</kbd> | Jobs: the queue of AI jobs. |
| <kbd>4</kbd> | Doctor: problems, and how to fix them. |
| <kbd>n</kbd> | Start a new job. |
| <kbd>c</kbd> | Cancel the job under the cursor. |
| <kbd>R</kbd> | Run the job under the cursor again. |
| <kbd>d</kbd> | Run the doctor's checks now. |
| <kbd>r</kbd> | Read the lab again now. |
| <kbd>q</kbd> | Quit. |

To move around, use the arrow keys or Vim's keys:

| Keys | What they do |
|---|---|
| <kbd>↓</kbd> <kbd>↑</kbd> or <kbd>j</kbd> <kbd>k</kbd> | Move down or up a list: the cards on Status, or a table's rows. On Status, each card shows as you reach it. |
| <kbd>→</kbd> <kbd>←</kbd> or <kbd>l</kbd> <kbd>h</kbd> | On Status, move between the cards and the card's detail. |
| <kbd>g</kbd> <kbd>G</kbd> | Go to the first or last item. |
| <kbd>Ctrl</kbd>+<kbd>D</kbd> <kbd>Ctrl</kbd>+<kbd>U</kbd> | Move a page down or up in a table. |
| <kbd>]</kbd> <kbd>[</kbd> or <kbd>L</kbd> <kbd>H</kbd> | Go to the next or previous tab. |

Hover over anything for what it is.

Or print the same information:

```bash
bromigos lab status           # one line for each part of the lab
bromigos lab models           # what each graphics card and model server holds
bromigos lab doctor           # what's wrong, and how to fix it
```

### As a hologram

Press <kbd>Super</kbd>+<kbd>Shift</kbd>+<kbd>H</kbd> for the lab deck: your lab as a
server rack, lit by the same readings. See [Holograms](holograms.md#lab-deck).

### In Settings

**Settings › Lab** shows the same summary, your models, recent jobs, the doctor, and where
AI runs.

## Make things on your lab

Send a job to your lab's graphics cards:

```bash
bromigos lab run image --prompt "a lighthouse at dusk"
bromigos lab run cutout --input ~/Pictures/robot.png
bromigos lab run upscale --input ~/Pictures/robot.png --scale 2
bromigos lab run hologram --prompt "a brass telescope"
bromigos lab run voice --text "The relays are lit."
bromigos lab run transcribe --input ~/Downloads/talk.m4a
```

| Job | What it makes |
|---|---|
| `image` | A picture from your description. |
| `image-edit` | A changed copy of a picture. |
| `cutout` | A picture with its background removed. |
| `upscale` | A bigger, sharper copy of a picture or a short video clip. Twice the size, or up to four times with `--scale`. |
| `3d` | A 3D model, from a picture of an object. |
| `hologram` | A hologram, from a description or a picture. To show it in the gallery, copy it into `~/.config/bromigos/vector/holo/`. |
| `voice` | Spoken audio of your text. |
| `transcribe` | Text from a recording. |
| `video` | A short looping video, from a picture and a description of how it moves. |
| `batch-llm` | Answers from a language model, for many prompts at once. |

`bromigos lab run --kinds` lists what your lab can do, and says why when it can't do
something.

When a job is done, a notification tells you. The result goes in
`~/Pictures/bromigos/lab/`, in a folder for each kind of job.

You can also ask [VECTOR](vector.md) for a picture, a hologram or a voice line "on the
lab". His jobs show in the queue as his.

### The job queue

```bash
bromigos lab jobs              # what's queued, running and done
bromigos lab jobs watch        # follow the queue until it settles
bromigos lab jobs cancel ID    # cancel a job
bromigos lab jobs retry ID     # run a job again
```

Jobs take turns. One heavy job runs at a time, and only when a graphics card has room for
it. VECTOR's voice always keeps its share. A job that has to wait says why.

### It's free unless you say otherwise

Jobs run on your lab, which costs nothing. A paid cloud service is only used for a job if
you add `--cloud` to it.

## Models

```bash
bromigos lab models                   # what each machine holds
bromigos lab models load NAME         # load an Ollama model
bromigos lab models unload comfyui    # free what ComfyUI holds
bromigos lab models recommend         # better models that fit your graphics cards
```

## YouTube downloads

If your lab runs [Pinchflat](homelab.md), it downloads YouTube channels and playlists into
your media library. Then they play in Jellyfin or Plex, like your other shows. You can run
it from here without opening its web page.

### Add a channel or a playlist

```bash
bromigos lab youtube add https://www.youtube.com/playlist?list=PLCFE9837C2F7EB8AA
bromigos lab youtube add https://www.youtube.com/@NASAGoddard --since 2025-01-01
```

It says what it will download. A playlist keeps its order. A channel gets every upload.

- It works out from the address whether it's a playlist or a channel. If it can't, add
  `--playlist` or `--channel`.
- `--since 2025-01-01` skips videos uploaded before that date. It's worth it for a big
  channel.
- `--name NAME` sets its name in Pinchflat, on disk and in your media server.
- `--quality` sets the most it downloads. See below.

In the dashboard (`bromigos lab`), the **YouTube downloads** card has an **Add a channel or
playlist…** button. It does the same thing. The key is `a`.

### Look after them

```bash
bromigos lab youtube list                      # each one: kind, quality, videos, last check, newest video
bromigos lab youtube status                    # the download queue, failures, recent downloads
bromigos lab youtube refresh "Little SDO"      # check for new videos now (leave out the name: all of them)
bromigos lab youtube pause "Little SDO"        # stop checking and downloading; resume starts it again
bromigos lab youtube remove "Little SDO"       # stop downloading it; the videos stay
bromigos lab youtube remove "Little SDO" --delete-files   # and delete its videos too
```

`remove` asks before it does anything. Your videos stay on disk unless you add
`--delete-files`. After a removal, the playlist in Jellyfin and Plex goes at the next sync.

Every command takes `--json`.

### Quality and disk space

Videos download at up to 1080p unless you say otherwise. Higher quality costs disk space.
As a rough guide, for an hour of video:

| Quality | About |
|---|---|
| `480p` | 0.3 GB |
| `720p` | 0.5 to 1 GB |
| `1080p` | 1 to 2 GB |
| `1440p` | 2 to 3.5 GB |
| `2160p` (4K) | 5 to 10 GB |
| `audio` | 0.06 GB (sound only) |

These come from the sizes YouTube offers for each quality, in the formats Pinchflat picks.
Fast-moving or 60-frames-a-second video sits at the top of each range. Talking heads and
slides sit at the bottom. `best` takes the highest a video has, up to 8K.

- `add --quality 2160p` downloads a new source in 4K.
- `bromigos lab youtube quality "Little SDO" 2160p` changes an existing one. Only new
  downloads change. The videos you already have stay as they are.
- To change the default for everything you add, set it in `homelab.toml`:

  ```toml
  [youtube]
  quality = "1440p"
  ```

### If YouTube asks Pinchflat to sign in

Sometimes YouTube stops a lab's downloads with "Sign in to confirm you're not a bot".
Pinchflat can then use a browser's YouTube cookies.

1. Sign in to YouTube with a **spare Google account**. Never use your main one: YouTube
   can block an account whose cookies a downloader uses.
2. Export its cookies in the `cookies.txt` format, with an exporter add-on for your
   browser.
3. Give them to your lab:

   ```bash
   bromigos lab youtube cookies set ~/Downloads/cookies.txt
   ```

4. Delete the exported file. Your lab keeps its own copy.

`set` checks the file and never shows the cookies. It turns on **When Needed** cookies for
every channel and playlist, so Pinchflat only uses them when YouTube asks.

- `bromigos lab youtube cookies status` says whether there are cookies and how old they
  are. After about 30 days it reminds you to export fresh ones.
- `bromigos lab youtube cookies clear` removes them and turns their use off.

Where the cookies go depends on your lab. See [Homelab](homelab.md#youtube-downloads-with-pinchflat).

### Playlists in Jellyfin and Plex

- `bromigos lab youtube` shows the **YouTube downloads** card: how many videos are
  waiting, any that failed, and the newest video from each channel and playlist. The
  dashboard's Status tab has the same card. Hover over a row for more.
- `bromigos lab youtube sync` makes each downloaded YouTube playlist a playlist in Jellyfin
  or Plex, in the same order as on YouTube. Run it as often as you like: it only changes
  what's different. To see what it would do first, add `--dry-run`.

The Status tab's **Storage** card shows each share on your NAS that the lab uses, which
NAS it's on, and how much space is free.

ComfyUI keeps the last job's models in memory until something frees them.
`bromigos lab models unload comfyui` frees them now. To find the best open models for your
graphics cards, see [Lab models](lab-models.md).

## Shortcuts to other commands

- `bromigos lab connect` is the same as `bromigos setup homelab`.
- `bromigos lab target` is the same as `bromigos target`. See
  [Creating with AI](where-ai-runs.md).

## If something's wrong

- **"The queue's service isn't running."** `bromigos lab run` tries to start it. If it
  still isn't running, run `systemctl --user start bromigos-lab.service`. To keep it
  running, run `systemctl --user enable --now bromigos-lab.service`.
- **A job waits for memory.** Something else is using the graphics card: another job, or a
  model someone loaded. The job starts by itself when there's room. `bromigos lab models`
  shows what's using it.
- **A card says "unreachable".** That service didn't answer. `bromigos lab doctor` says what
  to check.
