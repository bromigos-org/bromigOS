# Extensions

An extension adds something to bromigOS that it doesn't ship. It can be a theme, a deck,
a desktop panel (widget), a tool for VECTOR, a homelab adapter, a command or a hook. You
install it from a Git repository with `bromigos ext`. Updates show you what changed, and
ask again if the extension wants to do more than before.

This page covers how extensions work and how to make one. For installing and managing
them as a user, see the manual's [Extensions](../manual/src/extensions.md) page.

An extension is a Git repository, or a folder in one, with a manifest called
`bromigos-ext.toml` at its root. A *deck* is a full-screen holographic view drawn by the
*live layer*, the program behind the animated background. VECTOR is the desktop's AI
assistant. The [glossary](../manual/src/glossary.md) has the other terms.

## Install an extension

```bash
bromigos ext search                                      # browse the catalog
bromigos ext install hello-deck                          # install by name from the catalog
bromigos ext install https://github.com/you/thing@v1.0   # or from any Git URL, pinned to a tag
bromigos ext list                                        # what's installed, and its state
bromigos ext update --all                                # show what changed, ask, then update
bromigos ext remove thing
```

`bromigos theme install` does the same as `bromigos ext install`. A theme repository
without a manifest still installs, as a theme.

You can also do this without a terminal:

- **The Extensions window.** Run `bromigos extensions`, or open Extensions from the app
  launcher. It lists what's installed, then the catalog, with previews. Pick an
  extension to install, update, turn off, turn on, inspect or remove it. Each action runs
  `bromigos ext` in a terminal that stays open, so you can read what it says.
- **The menu.** Press Super+Space, then INSTALL › Extension… or REMOVE › Extension….
- **The theme switcher.** Themes from the catalog appear after your own, with a CATALOG
  badge. Picking one installs it.
- **Settings.** The Extensions page shows the same list as the Extensions window.

<!-- site:extension-kinds -->
## What an extension can contain

Each part of an extension has a *kind*. `bromigos ext` links each part into its own
folder under `~/.local/share/bromigos/ext/active/`, where the matching loader finds it.

| Kind | What it is | Linked as | Read by |
|---|---|---|---|
| `theme` | A theme folder: `colors.toml`, `theme.toml`, backgrounds, maybe a world | `themes/<name>` | `bromigos theme`, the theme switcher |
| `live-deck` | A deck: one `.py` file defining `DECK` | `live/decks/<name>.py` | `bromigos-live plugin <name>` |
| `live-layer` | A shader layer: `<name>.frag` and its `.json` | `live/layers/<name>.frag` and `.json` | The live background |
| `widget` | A panel: one `.py` file with a `panels.Panel` subclass ([what the gallery shows](plugins.md#what-the-gallery-shows)) | `widgets/<name>.py` | `bromigos-widgets` |
| `vector-tool` | A VECTOR plugin whose `register(vector)` adds tools | `vector/<name>.py` | VECTOR, when he starts |
| `vector-memory` | A VECTOR plugin whose `register(vector)` adds a memory store | `vector/<name>.py` | VECTOR, when he starts |
| `vector-skill` | A skill: `<name>.md`, or a folder with a `SKILL.md` | `skills/<name>` | VECTOR's skill catalog |
| `homelab-adapter` | A `registry.Adapter` for one kind of service | `homelab/<name>.py` | The homelab integrations |
| `command` | An executable named `bromigos-<group>[-<name>]` | `bin/<file>` | `bromigos <group> <name>`, the menu |
| `hook` | An executable run after every `bromigos theme set` | `hooks/theme-set.d/<extension>--<file>` | `bromigos theme set` |

A theme's holograms go in its `holo/` folder. VECTOR's gallery shows them on that
theme's shelf. A homelab adapter can also add status cards, health checks and job kinds
to `bromigos lab` ([lab.md](lab.md)).

Each loader reads bromigOS's own files first, then yours, then the extensions'. So an
extension can add something but never replace it. `bromigos ext` refuses a part whose
name is already taken.

## Commands

Every command takes `--json`.

| Command | What it does |
|---|---|
| `bromigos ext install <source>` | Installs an extension. |
| `bromigos ext list` | Lists installed extensions, with name, version, kinds, commit, state and source. |
| `bromigos ext info <name or source>` | Shows one extension's record, or what a source would install. |
| `bromigos ext update <name>` | Updates one extension. `--all` updates every one. |
| `bromigos ext remove <name>` | Removes an extension's links and its checkout. |
| `bromigos ext disable <name>` | Unlinks its parts but keeps the checkout. |
| `bromigos ext enable <name>` | Checks its files, then links its parts again. |
| `bromigos ext search [<term>]` | Lists the catalogs' extensions. |
| `bromigos ext new <kind> <name>` | Makes a working starter to edit. |
| `bromigos ext validate [<folder>]` | Checks a folder the way `install` would. |
| `bromigos ext migrate` | Converts themes installed before extensions existed. |

### Sources and versions

`install` takes any of these:

- A Git URL that starts with `https://`, `ssh://` or `file://`, or the form
  `git@host:path`.
- A folder on this machine.
- A name from a catalog, as `bromigos ext search` shows it.

Add `@<tag>`, `@<branch>` or `@<commit>` to pin a version, or pass `--ref`. Without one,
the extension follows the repository's default branch.

Other options:

- `--path <folder>` installs an extension that lives in a folder inside the repository.
- `--name <name>` names a theme repository that has no manifest.
- `--copy` installs a local Git repository's files as they are, uncommitted changes
  included, instead of its last commit.
- `--adopt` moves a theme of yours with the same name aside, then installs this one.

### States

`bromigos ext list` shows each extension's state:

- `ok` means everything is linked.
- `disabled` means you turned it off.
- `links missing` means some of its links are gone.
- `modified` means a file differs from what was installed. Only `--verify` checks this,
  because it reads every file.

`list` also names themes in `~/.config/bromigos/themes/` that didn't come from an
extension.

### Updates

`bromigos ext update` fetches the branch the extension follows. Then it shows you:

- the files added, changed and removed, and `git diff --stat`;
- any **new permissions** or new kinds of part;
- any hand edits to the installed copy that the update would replace.

It asks before it changes anything. Then it swaps the checkout in one step and relinks
the parts. `--check` shows the report and stops there.

An extension pinned to a tag or a commit doesn't move on its own. `update` says it's
pinned and lists any newer tags. Use `--ref <tag>` to move it.

`remove` refuses to remove the theme you're using. Switch themes first.

### After you install

Some parts take effect at once, and some need a nudge. `install` tells you which:

- A **theme** needs `bromigos theme set <name>`.
- A **deck** opens with `bromigos-live plugin <name>`.
- A **panel** appears within a few seconds.
- A **shader layer** draws within a few seconds, if its `.json` says `"enabled": true`.
- A **VECTOR plugin** loads when he next starts. Run `bromigos restart vector`.
- A **homelab adapter** loads when the homelab tools next start. It also needs a
  `[[source]]` of its type in `homelab.toml`.

## Where the files live

| Path | What it holds |
|---|---|
| `~/.local/share/bromigos/ext/src/<name>/` | The checkout, at the installed commit |
| `~/.local/share/bromigos/ext/active/<seam>/` | One link for each enabled part |
| `~/.local/state/bromigos/ext/ledger.json` | The ledger: the record of every extension |
| `~/.local/state/bromigos/ext/log.jsonl` | One line per install, update, enable, disable or remove |
| `~/.local/state/bromigos/ext/adopted/` | Your own themes that `--adopt` or `migrate` moved aside |
| `~/.cache/bromigos/ext/catalogs/` | Copies of the catalogs, fetched again after six hours |

The ledger records, for each extension:

- where it came from, the ref it follows and the commit installed;
- the sha256 of every file;
- the permissions it declared, and its parts and links;
- how it was approved, and when.

It also keeps a line for each extension you removed. The log goes to the journal too,
with the tag `bromigos-ext`.

When the extension is a folder inside a larger repository, the checkout holds the whole
repository.

Nothing is written into `~/.config/bromigos/`. That folder is yours, and it's often a
dotfiles repository, sometimes a public one. The usual `$XDG_DATA_HOME`,
`$XDG_STATE_HOME` and `$XDG_CACHE_HOME` variables move these paths.

## Trust and approval

**Themes install without a question.** An extension made only of themes is data.

**Everything else asks.** That covers code, shader layers and skills. `install` lists
the parts and the permissions the manifest declares. It installs only when you type yes
at a terminal. An update asks again, and shows what the extension may now do that it
couldn't before.

**There is no `--yes`.** The only way to approve without a terminal is a setup answers
file with `approve = true`:

```toml
[extensions]
install = ["https://github.com/you/thing@v1.0", "hello-deck"]
approve = true          # approve the ones that run code or reach VECTOR
```

Pass it to `bromigos setup --answers <file>` or `bromigos install --answers <file>`. The
ledger records that file's path and sha256 as the approval.

**The manifest must match what ships.**

- A part that runs code needs `code = true`.
- VECTOR tools or memory need a VECTOR level, `read` or `desktop`.
- An extension can never ask for VECTOR's terminal.

Declared hosts and paths are what the author says the extension reaches. bromigOS shows
and records them, but doesn't enforce them. An extension runs as you, like any program
you install.

### What's always refused

No approval gets past these:

- a part path that's absolute or climbs out with `..`;
- a part that's a symlink, or a manifest that's a symlink;
- a symlink anywhere in the extension that points outside it, or nowhere;
- a device, fifo or socket;
- compiled Python (`.pyc` or `__pycache__`), which could run instead of the source you
  read;
- a name that clashes with another extension, or with bromigOS's or your own plugins,
  commands and themes;
- a URL that isn't `https://`, `ssh://`, `git@host:path` or `file://`, such as `http://`,
  `git://` or `ext::`;
- an API range this bromigOS doesn't meet.

Git runs with no prompts and no hooks.

## VECTOR and extensions

VECTOR has a *guard*: safety code in his own repository (`holo/vector/guard.py`). It
protects his plugin folders, and his *sentinel* records every change to them in the
guard's audit log (`bromigos vector guard log`). It only records. Switching VECTOR off is
the operator's emergency switch alone. The extensions' `vector/` and `homelab/` folders
count as plugin folders too. Two rules let extensions work with the guard.

**The sentinel verifies exactly what `bromigos ext` recorded.** A new or changed file in
`active/vector/` or `active/homelab/` is logged as verified only if all of these hold:

- it's a link of an enabled extension;
- it points inside the extensions' checkouts;
- its content has the sha256 the ledger records.

A link's removal is verified only after the ledger drops it. An update first writes a
transaction to the ledger. For up to ten minutes, the sentinel accepts either version.
Then the checkout is swapped with a single `rename`. If you edit an installed VECTOR
plugin by hand, or plant a file there, the log records it as unverified.

**VECTOR can't install, update or approve extensions.** His terminal refuses these:

- `bromigos ext install`, `update`, `enable`, `disable`, `remove`, `migrate` and `new`;
- `bromigos theme install` and `bromigos theme remove`;
- `bromigos setup` and `bromigos install` with an answers file.

He may list, search, validate and read (`info`). In his sandbox, the extensions' folders
and the ledger are read-only, so the ledger the sentinel trusts is the one you wrote.

The VECTOR repository tests all of this in `tools/test-ext-guard.py`. It covers his
terminal's refusals, the sandbox, and the sentinel's audit through an install, an
update, a hand edit, a removal and a planted file, in a throwaway home folder.

## Make an extension

Start from a starter. Every kind has one, and each works as it is.

```bash
bromigos ext new live-deck my-deck          # makes ./my-deck
bromigos ext validate my-deck               # checks it as install would
bromigos ext install --copy ./my-deck       # installs your folder as it is
bromigos ext update my-deck                 # after an edit: copies the folder again
```

`--dir <folder>` puts the starter somewhere other than `./<name>`.

| Command | What the starter does |
|---|---|
| `bromigos ext new theme <name>` | A colour theme, teal on slate |
| `bromigos ext new live-deck <name>` | A deck showing this machine's load average, with hover hints and a `ping` verb |
| `bromigos ext new live-layer <name>` | A scan line over the background that speeds up with the CPU |
| `bromigos ext new widget <name>` | A panel showing the load average on seven-segment digits |
| `bromigos ext new vector-tool <name>` | A `<name>_uptime` tool at the read level |
| `bromigos ext new vector-memory <name>` | A memory store that keeps notes in a JSON-lines file |
| `bromigos ext new vector-skill <name>` | A skill on reading the load average |
| `bromigos ext new homelab-adapter <name>` | An adapter that reports this machine as a host |
| `bromigos ext new command <name>` | A `bromigos-<name>` command that says hello in the current theme |
| `bromigos ext new hook <name>` | A hook that writes the theme's name and accent colour to a file |

To start a theme from one you already have, run `bromigos theme new <name> --from
<theme>`. It copies that theme's files, with any overlays merged, under the new name.

### Try it without touching your desktop

| Kind | How |
|---|---|
| theme | `bromigos theme previews --dir <folder> --out preview.jpg` draws your desktop in it, offscreen. Run `bromigos theme set <name>` when you mean it. |
| live-deck | From a bromigOS checkout: `python live/tools/offscreen.py plugin:<name> out.png 2` |
| live-layer | In a checkout's `live/` folder: `python -m live.plugins test-layer <name or path.frag> out.png`. It compiles the shader headless and reports its GPU time. |
| widget | `bromigos-widgets render <name> out.png` |
| vector-tool, vector-memory | Import the module and call `register()` with a stand-in. The starter's docstring shows the interface. Then run `bromigos restart vector`. |
| homelab-adapter | Set `BROMIGOS_HOMELAB_CONFIG=test.toml` with a `[[source]]` of your type, then call `bromigos_homelab.caps.collect("hosts")`. |
| command, hook | Run the file. |

## The manifest

`bromigos-ext.toml` sits at the extension's root.

```toml
[extension]
name = "my-deck"                 # the id: lowercase letters, digits, - and _ (up to 64)
version = "0.1.0"
description = "What it is, in one line."
authors = ["You <you@example.com>"]
licence = "MIT"                  # "license" works too
homepage = "https://github.com/you/my-deck"
tags = ["deck"]

[requires]
bromigos = ">=1.0, <2"           # the extension API versions it works with

[[provides]]                     # one block per part
kind = "live-deck"               # a kind from the table above
path = "deck.py"                 # relative to this folder; "." for a theme at the root
name = "my-deck"                 # optional: the name it's linked under
# event = "theme-set"            # a hook's event; theme-set is the only one so far

[permissions]                    # what it reaches; shown before it installs
network = "none"                 # "none", "any", or a list such as ["api.example.com"]
filesystem = []                  # paths outside its folder that it reads or writes
# vector = "read"                # VECTOR tool level: "read" or "desktop"
code = true                      # true when any part runs code
```

`[extension]`, `[requires]` and at least one `[[provides]]` are required. An unknown
key is an error.

**The API version.** This bromigOS provides extension API **1.0.0**. If the range in
`[requires]` doesn't include it, `install` refuses and names both versions.

**Part names.** Without `name`, a part is linked under its file's stem or its folder's
name. Each kind has its own rule:

| Kind | Name rule |
|---|---|
| theme, live-deck, live-layer | Lowercase letters, digits, `-` and `_`, up to 64 characters |
| vector-skill | Lowercase letters, digits and `-`, up to 64 characters |
| widget | A Python module name, or the theme rule |
| vector-tool, vector-memory, homelab-adapter | A Python module name: lowercase letters, digits and `_`, 3 to 40 characters, starting with a letter |
| command | `bromigos-<group>[-<name>]` in lowercase words joined by `-`. It must be executable. |
| hook | Any file name. It must be executable, and it's linked as `<extension>--<file>`. |

Give a command a `# bromigos:summary=` header line. Without one, `bromigos commands` and
the menu show it bare. Add `# bromigos:menu=GROUP:Label` to put it in the menu
([menu.md](menu.md)).

**Permission hosts.** Each host is a name, `*.domain` or `host:port`, such as
`*.lab.example:8443`.

The catalog repository has a JSON Schema of the manifest, for an editor's TOML support,
at `schema/bromigos-ext.schema.json`.

## Publish an extension

1. Put it in a Git repository, with `bromigos-ext.toml` at the root and a licence and a
   README beside it. If it's a folder in a bigger repository, people install it with
   `--path`. Commit the executable bit of commands and hooks.
2. Tag releases so people can pin one:

   ```bash
   git tag v1.0.0 && git push --tags
   ```

   People then install `bromigos ext install <url>@v1.0.0`. Without a tag, installs
   follow your default branch, and `bromigos ext update` brings people your latest
   commit after showing it to them.
3. To list it in the catalog, add an `[[extension]]` entry to `index.toml` in
   [bromigos-org/extensions](https://github.com/bromigos-org/extensions). Include a
   preview. For a theme, use the switcher's own picture:
   `bromigos theme previews --dir <theme> --out previews/<name>.jpg`. Run the catalog's
   `tools/check.py`, then open a pull request.

If you add a permission later, everyone's next update shows it under **NEW
PERMISSIONS**, and they decide again.

## Catalogs

`bromigos ext search` reads bromigOS's catalog,
[bromigos-org/extensions](https://github.com/bromigos-org/extensions). To use others,
list them in `~/.config/bromigos/ext.toml`:

```toml
catalogs = ["https://github.com/bromigos-org/extensions", "/home/me/my-catalog"]
```

`$BROMIGOS_EXT_CATALOGS`, a space-separated list, overrides both.

A catalog is a Git repository, or a folder, with an `index.toml`:

```toml
schema = 1

[[extension]]
name = "hello-deck"                         # as its manifest says
description = "A full-screen hologram of this machine's load average."
kinds = ["live-deck"]
url = "https://github.com/bromigos-org/extensions"
path = "examples/hello-deck"                # its folder, when not the repository's root
# ref = "v1.0.0"                            # pin a tag or branch
preview = "previews/hello-deck.png"         # a file in the catalog, or an https URL
tags = ["example", "deck"]
# bundled = true                            # ships with bromigOS: listed, nothing to install
```

`search` marks each entry `(installed)` or `(ships with bromigOS)` where that applies.

When an `https://` GitHub URL needs a login, `bromigos ext` tries the same repository
over SSH with your key. Git never prompts.

## Themes installed before extensions

Before extensions existed, `bromigos theme install` copied a theme into
`~/.config/bromigos/themes/<name>` without its Git history, so it never updated.
`bromigos ext migrate` fixes that. A migration runs it once during `bromigos update`.

For each such theme that a catalog offers, `migrate` checks the files match exactly.
Then it installs the theme as an extension and moves the old copy to
`~/.local/state/bromigos/ext/adopted/`. `--dry-run` only says which themes it would
move.

Themes it can't match stay where they are. They're your own, or came from somewhere
else. `bromigos ext list` names them, and `bromigos ext install <its url> --adopt` brings
one in.
