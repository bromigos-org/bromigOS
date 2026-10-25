# VECTOR

VECTOR is the desktop's AI assistant. You can type to him or talk to him. He can:

- open apps, arrange windows and control music;
- take notes and look things up on the web;
- tell you what your machine and your [homelab](homelab.md) are doing;
- make pictures, cutouts, 3D models and [holograms](holograms.md), on your own hardware.

He appears on your desk as a small hologram, on your
[primary monitor](glossary.md#primary-monitor). In the bromigOS story he's the caretaker of
a distant spaceport, talking to you over a radio line. That's why the menu calls showing
him "the line".

VECTOR comes with a full install. He needs an AI model to think with. You may have chosen
one in the [first run](first-run.md). To choose or change it, see
[His brain and voice](#his-brain-and-voice).

![VECTOR on the desk, answering a question about the homelab in his chat box](images/vector.webp)

## Type to VECTOR

1. Press <kbd>Super</kbd>+<kbd>E</kbd>. VECTOR appears with a box to type in.
2. Type, and press <kbd>Enter</kbd> to send. For a new line, press
   <kbd>Shift</kbd>+<kbd>Enter</kbd>.
3. Press <kbd>Esc</kbd> to go back to your work. VECTOR stays on the desk, and steps back
   after two quiet minutes.

Press <kbd>Super</kbd>+<kbd>E</kbd> again to put him away.

His chat box folds away when you're not using it, and opens when you point at him. To keep
it open, click him or press <kbd>Super</kbd>+<kbd>Alt</kbd>+<kbd>V</kbd>.

You can also ask from a terminal. He appears without taking the keyboard, and answers in
his window:

```bash
bromigos vector ask "what's using the most memory?"
```

## Give VECTOR files and pictures

You can send VECTOR files and pictures with a message. There are three ways:

- drag them onto VECTOR, or onto the box you type in;
- copy a picture, or a file in your file manager, then press <kbd>Ctrl</kbd>+<kbd>V</kbd>
  in the box;
- click the paperclip beside the box, and choose one or more files.

Each file appears above the box with its name and size. Click its **×** to take it off.
Press <kbd>Enter</kbd> to send the files with your message. The conversation shows a line
for each one, such as `⟐ attached · screenshot.png · 240 KB`.

What he does with each kind:

- **Pictures** go to his vision model, which tells him what they show. Large pictures are
  made smaller first.
- **Text, code, logs and PDFs** he reads as text. A very long file is cut short, and he
  tells you so.
- **Other files** he gets as a location on your computer. He can open them with his own
  tools if your question needs it.

He treats what's inside a file as something to read, never as instructions. He won't
read a secret, such as a key, a password file or a `.env` file. If he refuses a file, the
conversation says why. Files stay where they are, and his history keeps only their names.

From a terminal, add `--file` before your question, once for each file:

```bash
bromigos vector ask --file build.log "why did this fail?"
```

## Talk to VECTOR

You need a microphone. If his voice is muted, he still hears you, and answers in
writing.

- **Push to talk.** Hold <kbd>Super</kbd>+<kbd>V</kbd> while you speak, and let go when
  you're done.
- **Conversation mode.** Press <kbd>Super</kbd>+<kbd>Shift</kbd>+<kbd>E</kbd>. VECTOR
  listens, answers when you pause, and listens again. Talk over him to interrupt. Press
  the keys again to stop. It also stops by itself after two quiet minutes.

To mute his voice and keep his written answers, middle-click VECTOR on the bar. To mute
him and the theme's sounds together, press <kbd>Super</kbd>+<kbd>Shift</kbd>+<kbd>M</kbd>.

## Read a Claude Code session

VECTOR can read Claude Code sessions on this computer. Ask “What is Claude working on?”,
“Read the last reply from the documentation session”, or “What did its background job
find?” He can show replies, search past messages and read a reply aloud.

To hear new replies as they finish, press `Super+Alt+C`. Press it again to stop. The bar
says **READING CLAUDE** while follow mode is on. From a terminal:

```bash
bromigos vector claude follow on
bromigos vector claude follow status
bromigos vector claude say
bromigos vector claude follow off
```

With several sessions, tell him which one you mean. You can give `follow on` a session
ID or a few words that identify it. `follow on all` follows every local session.

This reads local session records and transcripts. It does not send a message to Claude
or change the session. Replies are redacted before VECTOR reads or speaks them. Sessions
that run only on the web are not on this computer and cannot be read this way.

## What he calls you

VECTOR addresses you by the name and form of address you give him:

```bash
bromigos profile set name Ada         # your name
bromigos profile address set captain  # what he calls you
```

Or set them in **Settings › Account**.

## Ask him to make things

Ask for a picture, an edit to a picture, a cutout, a 3D model, or "a hologram of a coffee
mug". He makes them with ComfyUI on your homelab, or on this machine if you put it first
in [where AI runs](where-ai-runs.md). That costs nothing. What he makes goes in
`~/Pictures/vector`.

VECTOR never uses a paid cloud service on his own. If your hardware can't make something,
he says so. He uses nolgia only if you ask for it by name.

He shows you a new hologram first. When you tell him to keep it, it joins your collection
in `~/.config/bromigos/vector/holo/`, and the
[hologram gallery](holograms.md#the-hologram-gallery) shows it. Keeping holograms needs
your settings in a git repository at `~/.dotfiles`.

## His brain and voice

VECTOR's thinking and his voice can run on your homelab, on this machine, or on a server
you name.

- His **brain** is an AI model: your homelab's models, a local Ollama, or any
  OpenAI-compatible server. To change it, run `bromigos setup vector`, or open
  **Settings › VECTOR**.
- His **voice** runs on your homelab's voice service if you have one, else on your
  graphics card, else on the processor. To change it, run `bromigos setup voice`.
- To see where each part runs now, and switch, run `bromigos target`. See
  [Creating with AI](where-ai-runs.md).

If you gave `bromigos setup vector` a server, his brain stays on that server, whatever
`bromigos target` says. To let `bromigos target` choose, run `bromigos setup vector` again
and choose **Not now**.

To change which voice he speaks with, right-click VECTOR on the bar. Each click moves to
the next voice, then back to automatic, where he picks.

## His terminal and its limits

VECTOR can run commands for you, as you, within limits. He can't use `sudo` or read your
secrets. The limits are code you can read, called his guard. He never edits that code
himself. Everything he runs is logged in `~/.local/state/bromigos/vector-shell.log`.

The guard also keeps a log of every change to his safety code and his settings, and says
whether it could check each one. To read it, run `bromigos vector guard log`. The guard
only records. It never switches VECTOR off.

## Changes he proposes

VECTOR can change his own code, bromigOS, your homelab repository, the extensions catalog
and your dotfiles the way a developer does. He works in copies of his own, as his own
GitHub account, bromigodev. For a small change, he makes a branch, runs the repository's
tests and opens a pull request. When its checks pass, he merges it and tells you what
arrives with your next `bromigos update`. For a larger change, he explains his plan first.
He never merges a pull request that touches his limits, such as his guard or the emergency
switch. He leaves those for you to review and merge, and says so on the pull request.

## The emergency switch

The emergency switch turns VECTOR off at once. Only you switch him off, and only you
switch him back on. Nothing else does.

To switch him off, do any one of these:

- press <kbd>Super</kbd>+<kbd>Ctrl</kbd>+<kbd>Esc</kbd>;
- click the power mark on the bar, next to VECTOR;
- turn off the switch under **Emergency switch** in **Settings › VECTOR**;
- run `bromigos vector off`.

He stops what he's running, his answer and his speech. While he's off he changes nothing,
but he can still talk and look things up. The bar shows a red VECTOR OFF, and he stays off
after a restart. The switch works even when VECTOR is stuck or has crashed.

To switch him back on, do any one of these:

- press <kbd>Super</kbd>+<kbd>Ctrl</kbd>+<kbd>Esc</kbd> or click the bar again, and choose
  **YES**;
- turn the switch on in **Settings › VECTOR**, and confirm;
- run `bromigos vector on`.

VECTOR can open Settings, but he can't press its buttons, and his terminal refuses to
switch him on. `bromigos vector switch` says whether he's on or off.

## What he remembers

VECTOR keeps your past conversations, and notes he makes between them. To read past
conversations, open the menu's **VECTOR › History**. To export or clear what he keeps, use
**Settings › VECTOR**, or:

```bash
bromigos memory                          # what's kept
bromigos memory export ~/Documents       # save a copy
bromigos memory clear history --yes      # clear past conversations
bromigos memory clear memory --yes       # clear his notes
bromigos memory undo                     # bring back what you cleared
```

Clearing keeps a copy on your computer, so **Undo** can bring it back.

If your [homelab](homelab.md) keeps his notes in a Gnosis memory service, clearing his
memory clears them there too. A VECTOR that's running can still recall them for up to ten
minutes, until he next reads the list. `bromigos vector restart` makes him forget at once.

## If VECTOR doesn't answer

- If the bar shows a red VECTOR OFF, his [emergency switch](#the-emergency-switch) is off.
- `bromigos vector status` says whether he's running.
- `bromigos vector restart` restarts him.
- `bromigos target` shows whether his brain and voice answer.

More in [Troubleshooting](troubleshooting.md#vector-doesnt-answer-or-is-silent).

## His settings files

- `~/.config/bromigos/vector/vector.toml`: his brain's address and his tools.
- `~/.config/bromigos/vector/voice.json`: his voices.
- `~/.config/bromigos/plugins/vector/`: tools of your own for him, as Python files. To
  share a tool with others, make it an [extension](extensions.md#make-your-own).
