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
