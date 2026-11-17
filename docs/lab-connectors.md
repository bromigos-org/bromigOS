# The connector catalogue: bromigos lab connectors

The connector catalogue is a list of outside services that an AI agent in your lab could
use, such as Stripe, Notion or GitHub. For each one it says where the service is reached
and what it needs from you. `bromigos lab connectors` lists it, searches it and shows one
entry.

This page explains the catalogue's data, its command and how it's made, for someone
extending it. An *agent* here is a program that works through a task by calling tools,
such as the ones in [Agents in your lab](lab-agents.md).

> **Planned.** Connecting an entry to a running agent isn't built yet. Today the catalogue
> only tells you what exists and what each entry needs. Nothing here signs in to a
> service, asks for a key, keeps a key or sends anything to a service.

## Two kinds of entry

| Kind | What it is | Entries |
|---|---|---|
| `one-click` | A remote MCP server: one web address an agent connects to. | 74 |
| `key` | A service with a REST API and no MCP server. An agent calls the API with a key. | 38 |

*MCP* is the Model Context Protocol, a standard way for an agent to call a service's
tools. A one-click connector needs nothing, an API key, or a sign-in in your browser. A
key platform needs an API key that you make on the service's own site.

Four services are in both tables: Airtable, GitHub, Notion and Stripe. Their ids are the
same, so `show` prints both entries.

## Browse the catalogue

To list what's on offer, by category:

```bash
bromigos lab connectors
```

Each line has the entry's id, its name, what it needs and a summary. For a one-click
connector the third column is `no sign-in`, `a key` or `a sign-in`. For a key platform
it's the environment variable its key goes in.

| Command | What it does |
|---|---|
| `bromigos lab connectors list` | List the entries on offer. This is the default. |
| `bromigos lab connectors list --kind one-click` | List one kind: `one-click` or `key`. |
| `bromigos lab connectors list --category design` | List one category, by its name or a part of it. |
| `bromigos lab connectors list --all` | Add the entries that aren't on offer, and say why. |
| `bromigos lab connectors search <words>` | Find entries by id, name or alias. |
| `bromigos lab connectors show <id>` | Show one entry in full. `--kind` picks one of two. |

Every command takes `--json`. The JSON has a `rows` list. Each row is the entry's own
keys, plus `kind`, `state` and `needs`, a sentence that says what the entry needs.

`show` prints these for a key platform:

- the environment variable its key goes in, and the header the key is sent in;
- its documentation and its API's base address;
- its note, and its API notes when it has them.

For a one-click connector it prints the address, the kind of sign-in, and whether the
address answered when it was last checked.

`search` looks at ids, names and aliases only. An *alias* is another word people type
for a service, such as `jira` for the Jira & Confluence entry. The closest match comes
first: a whole name, then a whole alias, then a part of either.

The command ends with one of these codes:

| Code | Means |
|---|---|
| 0 | Done. A search that finds nothing is still 0. |
| 2 | The command line was wrong. |
| 3 | No entry has that id, or no single category matches. |
| 4 | The catalogue can't be read, or it has problems. The message names each one. |

## Which entries are on offer

`list` shows the entries that are on offer. `list --all` and `search` show every entry
with its state.

| State | Means | Entries |
|---|---|---|
| `offered` | The entry is a standard server or API that needs nothing of our own. | 63 connectors, 38 platforms |
| `listed only` | It needs a sign-in or code of bromigOS's own, which isn't built. | 9 connectors |
| `no address` | It has no server of its own. Another connector reaches it. | 1 connector |
| `no answer` | Its address didn't answer when it was last checked. | 1 connector |

"On offer" doesn't mean connected. It means nothing stands in the way once connecting is
built.

The nine `listed only` entries are these:

- **Seven Google entries.** Selected Google files, Gmail, Gmail (send only), Google Drive,
  Google Calendar, Google Docs and Google Sheets. Their addresses are Google's own APIs,
  not MCP servers. They need a Google sign-in that bromigOS registers with Google, and
  tools of our own on top.
- **Gmail (app password).** It needs mail tools of our own that speak IMAP and SMTP.
- **GitHub.** Its server is a real MCP server. But GitHub doesn't let a program register
  its own sign-in, so it needs a GitHub sign-in that bromigOS registers.

The source lists the other sign-in entries as servers that register a sign-in by
themselves, so they should need nothing from us. bromigOS hasn't checked that yet.

Jira & Confluence has no address. Its `via` key names Zapier, the connector that reaches
it.

## The liveness check

Each connector's address was asked once, on the day in the file's `checked` key. The
answer is recorded in the entry, as `answered` and `answer`.

The check sends one `GET` request to each address. It sends no credentials and nothing
about your machine: its `User-Agent` is a generic one. It doesn't follow redirects, and it
reads nothing but the status.

| The address | Recorded as |
|---|---|
| Gives any status but 404, 410 or one from 500 up | `answered = true`, with the status |
| Gives 404, 410 or a status from 500 up | `answered = false`, with the status |
| Has a host that doesn't resolve | `answered = false`, `host not found` |
| Doesn't connect, times out or fails TLS | `answered = false`, with the reason |

Most servers answer 401 or 405 to a bare `GET`. That's enough: something is there. An
answer doesn't prove the server works with an agent.

Two entries are never asked. Unreal Engine's server runs on your own machine, and Jira &
Confluence has no address.

On 2026-11-17, 65 of the 72 entries that were asked answered. The seven that didn't:

- Six of the nine `listed only` entries: five Google API addresses and Gmail (app
  password). None of those addresses is an MCP server.
- Replaid, whose address failed TLS. It's the one `no answer` entry.

## The file

The catalogue is `homelab/share/lab/connectors.toml`. The `bromigos-lab` package installs
it as `/usr/share/bromigos/homelab/lab/connectors.toml`. To read another file instead,
set `BROMIGOS_LAB_CONNECTORS` to its path.

Don't edit the file by hand. A script makes it. See
[Import the rows again](#import-the-rows-again).

The top of the file has four keys:

| Key | Holds |
|---|---|
| `format` | The file's format, `1`. Another number is refused. |
| `checked` | The day of the liveness check. |
| `connector_categories` | The one-click connectors' categories, in the order they're listed. |
| `platform_categories` | The key platforms' categories, in the order they're listed. |

Each one-click connector is a `[[connector]]` table:

| Key | Holds |
|---|---|
| `id`, `name`, `category` | Its id, its name and one of `connector_categories`. Required. |
| `auth` | `none`, `key` or `sign-in`. Required. |
| `url` | Its address. It's `https`, except on a `local` entry. |
| `via` | For an entry with no `url`: the id of the connector that reaches it. |
| `local` | `true` when the server runs on your own machine. |
| `official` | `true` when the service's own maker runs the server. Required. |
| `homepage` | The service's site. Required. |
| `key_header` | The header a key goes in, when it isn't `Authorization: Bearer`. |
| `aliases` | Other words people type for it. |
| `summary` | One or two sentences on what it does. Required. |
| `listed_only` | Why bromigOS can't offer it yet, as a sentence. |
| `answered`, `answer` | The liveness check's result. Absent when the address is never asked. |

Each key platform is a `[[platform]]` table:

| Key | Holds |
|---|---|
| `id`, `name`, `category` | Its id, its name and one of `platform_categories`. Required. |
| `env` | The environment variable its key goes in, such as `PRINTIFY_API_KEY`. Required. |
| `docs`, `api_base` | Its API's documentation and base address. Required. |
| `api_via` | The API it's reached through, when it has none of its own. |
| `auth_header` | How the key is sent, as a header line: `Authorization: Bearer ${PRINTIFY_API_KEY}`. |
| `unattended` | `false` when a key alone can't run it unattended. |
| `aliases`, `summary` | As for a connector. `summary` is required. |
| `note` | What to know before you use it. |
| `api_notes` | Checked notes on the API itself, for whoever calls it. |

### What the loader refuses

The rows come from outside bromigOS, so the loader checks them before anything is
printed. It refuses the whole file, and names each problem, when it finds any of these:

- an id used twice in one table, or an environment variable used twice;
- an address that isn't `https`, or that carries a user name. A `local` entry may use
  `http`, on `127.0.0.1` or `localhost` only;
- an `auth` that isn't `none`, `key` or `sign-in`;
- an `env` that isn't capitals, digits and underscores, starting with a capital;
- a key the tables above don't list, a missing required key, or a value of the wrong
  kind;
- text with a control character in it.

## The module

`homelab/lib/bromigos_homelab/connectors.py` loads the file and answers questions about
it. The command is its `main`.

| Function | What it does |
|---|---|
| `load()` | Read and check the file. Raise `CatalogueError` when it has problems. |
| `validate()` | Return the problems as a list. An empty list means none. |
| `rows(cat, kind, category, every)` | The entries on offer, or all of them with `every=True`. |
| `search(cat, words, kind)` | The entries that match, the closest first. |
| `find(cat, id, kind)` | Every entry with that id. |
| `state(row)` | `offered`, `listed only`, `no address` or `no answer`. |
| `needs(row)` | What the entry needs, as a sentence. |

## Where the rows come from

The rows are derived from the catalogue of [StarNet](https://github.com/androoAGI/starnet),
which is licensed under MIT, Copyright (c) 2026 Andrew Sims. The MIT notice is in
`homelab/share/lab/LICENSE-starnet`. The `bromigos-lab` package installs it as
`/usr/share/licenses/bromigos-lab/LICENSE-starnet`.

bromigOS isn't part of StarNet, and StarNet doesn't endorse it. This is bromigOS's own
catalogue, made from StarNet's rows. The import changes four things:

- Keys get plain names, such as `env` and `api_base`.
- Keys that only StarNet's window or its own code uses are dropped.
- Entries that work only through StarNet's own code, or through a sign-in that StarNet
  registered, are kept and marked `listed_only`.
- Wording that names StarNet's own screens and tools is reworded.

The API notes are kept as they were checked, with the same rewording.

## Import the rows again

`tools/lab/connectors-import.py` makes the file. It reads two files in
`tools/lab/connectors/`:

| File | Holds |
|---|---|
| `starnet.json` | The source rows. The script's header says how to print them from StarNet. |
| `checked.json` | The liveness check's results, by connector id. |

To make the file again after changing either one:

```bash
tools/lab/connectors-import.py
```

The same input always gives the same file. `tools/lab/connectors-import.py --check`
changes nothing and fails when the file is stale.

The script reads `starnet.json` as data and runs nothing from it. It stops when a row has
a key it doesn't know, so a new key is kept or dropped on purpose. It also stops when
wording it rewords has changed upstream.

To run the liveness check again:

```bash
tools/lab/connectors-import.py --probe
tools/lab/connectors-import.py
```

`--probe` is the only part that uses the network. It sends one request to each address
and writes `checked.json` with today's date. Run it once. Don't run it in a loop.

## Tests

`homelab/tests/test_lab_connectors.py` covers the file, the module, the command and the
import script. Its liveness tests ask a server on the same machine, so nothing reaches a
network.

```bash
cd homelab
PYTHONPATH=lib python -m unittest tests.test_lab_connectors
```
