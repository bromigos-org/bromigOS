# How we write the docs

This guide covers every Markdown file in this repository: the README, CONTRIBUTING.md,
`docs/`, each folder's README and the manual. Read it before you write or change one.

The aim is simple. A reader should understand a page the first time through, without
knowing the project's history or its lore.

## 1. Know the reader

Each kind of document has one reader. Write for that person.

| Document | Reader | What they want |
|---|---|---|
| [README.md](../README.md) | Someone deciding whether to try bromigOS | What it is, what it looks like, what it needs, how to get it |
| [The manual](../manual/src/SUMMARY.md) (`manual/src/`) | Someone using bromigOS | How to do things on their desktop |
| `docs/` | A contributor, or someone extending bromigOS | How a part works, its files and formats, and where to plug in |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | Someone changing the code | How to build, test and send a change |
| A folder's README | Someone about to work in that folder | What the code there does, and how its files fit together |

Don't put user instructions in `docs/`, or design notes in the manual. Link across instead.

## 2. Say what it is first

Open every page with what the thing is and why it matters, in plain words. One or two
sentences. Then the details.

Lore is flavour. It comes after the facts, and briefly. A reader who has never heard of
the Drift should still understand every sentence.

> **Before:** In the universe, bromigOS is what runs on the Wick's console. VECTOR on the
> line, the decks and the Drift map, drawn by the live layer.
>
> **After:** bromigOS is a desktop based on Arch Linux and Hyprland. Its wallpaper is a
> living scene that reacts to your machine, and VECTOR, an AI with a voice, lives on your
> desk. (In the Bromigos stories, it's the software on a relay station's console.)

## 3. Short sentences, one idea each

- Use the active voice. "`bromigos update` takes a snapshot", not "a snapshot is taken".
- Put one idea in each sentence. If a sentence has three commas and a colon, split it.
- Don't chain clauses with colons or semicolons. Use a full stop.
- Don't nest parentheses. If an aside needs its own aside, it needs its own sentence.
- Don't stack nouns ("the snapper pre/post snapshot pair record file"). Say what it does.
- Use a list when you have a list. Three or more items in a sentence usually want bullets.

> **Before:** Every update is bracketed by a snapper pre/post snapshot on a btrfs root,
> and on GRUB the boot menu lists the snapshots (grub-btrfs), for a system that doesn't
> boot.
>
> **After:** bromigOS takes a snapshot before and after every update. If an update breaks
> something, `bromigos update --rollback` undoes it. If the machine won't boot, choose an
> earlier snapshot from the boot menu.

> **Before:** `install.sh` (~50 lines: the repository, its pinned key, `bromigos-core`)
> hands over to `bromigos install` (Rust: packages, services, configs by migration,
> desktop settings, the theme).
>
> **After:** `install.sh` is about fifty lines long, so you can read it before you run
> it. It adds the bromigOS package repository and installs the core package. Then it
> runs `bromigos install`, which does the rest.

## 4. Define every product term

The first time a page uses a bromigOS term, say what it means in a few words. Link to
the [glossary](../manual/src/glossary.md) for the full definition. Don't assume the
reader has read another page first.

These terms need it most:

| Term | Say something like |
|---|---|
| VECTOR | the desktop's AI assistant, with a voice |
| the live layer | the program that draws the animated background and the decks |
| a world | a theme whose wallpaper is a living scene (Mire, Tidewell) |
| the den | the default theme's wallpaper: a radio room with live screens |
| a deck | a full-screen holographic view you open with a key, such as the timeline |
| panels (widgets) | the small dashboards on the desktop. Write "panels (widgets)" the first time, since most readers say widgets |
| a colour theme | a theme that changes colours only, with no scene of its own |
| a channel | which builds a machine follows: `stable`, `rc`, `edge` or `dev` |
| an extension | a theme, deck, panel or tool installed with `bromigos ext` |
| the homelab integrations | the code that shows your own servers on the desktop |

Avoid internal shorthand altogether: "the reach batch", "phase 4 polish", "relay
console", "on the line". If a word only makes sense to someone who was there, replace it.

## 5. Lead with the task

Start with what the reader wants to do, then the command, then what happens.

> To change the theme, run `bromigos theme set mire`. Every app changes colour within a
> second.

- Make commands copy-pasteable. Put them in a fenced block with a language (`bash`,
  `toml`, `text`).
- Mark placeholders with angle brackets, such as `<repo>`, and say what goes there.
- Keep comments in a command block short. If a comment needs a sentence, write the
  sentence outside the block.
- Say what the reader will see afterwards, especially when nothing appears to happen.

## 6. Plain headings

Write headings in sentence case. Say what's under them.

| Before | After |
|---|---|
| The reach batch | Themes outside the desktop |
| Tuning into the relay | The boot menu |
| What happens | What the installer does |

## 7. Each fact in one place

Every fact has one home. Everywhere else links to it.

- The full key list lives in the manual's [Keys](../manual/src/keys.md) page. Other pages
  mention a key or two, then link.
- The command reference lives in [Commands](../manual/src/commands.md).
- Each file format is described once, in the `docs/` page for that part.

Tables are for reference rows: a key and what it does, a file and what it holds. A cell
holds a phrase or one short sentence. Never put a paragraph in a cell.

> **Before:** `| Super+Space | the menu: launch, install, setup, style, update, toggles
> (typing searches everything) |`
>
> **After:** `| Super+Space | Open the menu. Type to search apps, settings and commands. |`

## 8. Show it

bromigOS is a visual product, so show it. Put a screenshot next to the text that
describes it.

- Images live in [`docs/images/`](images/). Use WebP or JPEG, about 1600 pixels wide,
  and keep each file under about 400 KB.
- Use approved renders only. These are the published stills on bromigos.org and
  offscreen renders. Never take a screenshot of someone's real desktop.
- Show bromigOS only. No faces or likeness art, no real hostnames, no private data.
- Every image needs a "yes" row in [ASSETS.md](ASSETS.md).
- Write alt text that says what the picture shows, in a sentence.

## 9. Be accurate

Check every command, flag, path and key against the code before you write it down.

- Run `bromigos <command> --help` from a build (`cargo build -p bromigos` in `core/`).
- Read the source for paths, defaults and file formats.
- Don't describe what isn't built. Put planned work under a clear note:

  > **Planned.** `bromigos lab deploy` will change your homelab through its Git
  > repository. It isn't built yet.

- The generated sections (between `<!-- generated:… -->` markers) come from the code.
  Change the code, then run `tools/docs/generate.py`. Never edit them by hand.
- A `<!-- site:… -->` marker above a heading tells the bromigos.org export to read that
  section for the website. Rename or rewrite the section freely, but keep its marker
  above it. If the section moves, move the marker with it.

## 10. House style

- **British spelling.** Colour, licence (the noun), behaviour, organise.
- **The name.** Write bromigOS, with a lower-case b, even at the start of a sentence.
  bromigOS is *based on Arch Linux*. Never put "Arch" in the product's name.
- **Keys.** Write them as `Super+Space`, `Alt+Shift+Enter`, with a capital first letter.
- **Commands and paths** go in backticks: `bromigos update`, `~/.config/bromigos/`.
- **Links.** Use relative links inside the repository. Link to a page, not a line number.
- **Line length.** Wrap prose at about 90 characters, as the existing files do.
- **Nothing private.** No hostnames, LAN addresses, tokens, Vault paths or personal
  names. Examples use `example.org` and made-up names.
- **Other products.** BRODEC is a separate product; don't mention it here. The exceptions
  are its optional desktop app and its optional lab bridge, which bromigOS publishes: the
  "BRODEC (optional)" lines on the package pages, how they're published in
  packaging/README.md, and the lab bridge's chart in `homelab/charts/brodec-lab/`. Don't name
  other distributions as models or comparisons in user-facing pages.

## Before you commit

1. Read the page aloud, or at least in your head. Fix any sentence you stumble on.
2. Run `tools/docs/generate.py` if you changed a command's help, a key or a package.
3. Run `tools/docs/check-links.sh` to check every link and anchor.

CONTRIBUTING.md has the full commands, in
[Docs](../CONTRIBUTING.md#docs).
