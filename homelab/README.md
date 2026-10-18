# homelab/: the homelab integrations

This folder builds the standalone `bromigos-lab` package and the optional desktop
integrations in `bromigos-homelab`. The console runs on plain Arch Linux. One data layer asks for *capabilities*, kinds of readings such as
metrics, hosts or models. *Adapters* for real services, such as Prometheus or Kubernetes,
provide them. Nothing here knows anyone's hosts, and nothing is on until a source is
configured.

How it works, how to connect a homelab and how to write an adapter:
[docs/homelab.md](../docs/homelab.md). The lab console, `bromigos lab`:
[docs/lab.md](../docs/lab.md). For users: the manual's
[Your homelab](../manual/src/homelab.md).

## What's here

| Folder | Installed to | What it holds |
|---|---|---|
| `lib/bromigos_homelab/` | `/usr/lib/bromigos/lib/bromigos_homelab/` | the data layer, with the adapters in `adapters/`. Every consumer imports this one module. |
| `live/` | `/usr/lib/bromigos/homelab/live/` | the Lab, Mind, Ops and Netmap decks, as live-layer plugins |
| `widgets/` | `/usr/lib/bromigos/homelab/widgets/` | the LAB panel, and the generator for panels declared in `homelab.toml` |
| `vector/` | `/usr/lib/bromigos/homelab/vector/` | VECTOR's read-only homelab tools and his Gnosis memory, as a VECTOR plugin |
| `bin/` | `/usr/lib/bromigos/bin/`, with `/usr/bin/bromigos-lab` | `bromigos homelab`, `bromigos setup homelab` and `bromigos lab` |
| `applications/` | `/usr/share/applications/` | app launcher entries for the lab console and the homelab decks |
| `systemd/` | `/usr/lib/systemd/user/` | the job queue's service, and the model catalog's weekly timer |
| `share/homelab.toml` | `/usr/share/bromigos/default/homelab.toml` | the packaged default: every key documented, no sources |
| `share/lab/` | `/usr/share/bromigos/homelab/lab/` | the lab's data (below) |
| `holo/` | `/usr/share/bromigos/homelab/holo/` | the rack hologram ([holo/README.md](holo/README.md)) |
| `tests/` | not installed | unit tests against recorded API answers, and an end-to-end test |

`share/lab/` holds three data files:

- `models.toml` is the lab model catalog ([docs/lab-models.md](../docs/lab-models.md)). It
  ships in its own package, `bromigos-lab-catalog`, so it can update without a code
  release.
- `jobs.toml` records what each lab job kind measured on a real GPU
  ([docs/homelab.md](../docs/homelab.md#measured-kinds-jobstoml)).
- `profiles.toml` is the service catalog and presets for `bromigos lab provision`
  ([docs/lab-provision.md](../docs/lab-provision.md)). It includes Hermes and OpenClaw
  containers using an existing model endpoint, and an experimental NemoClaw host plan.
  [Agent installer notes](../docs/lab-agents.md) explain configuration, credentials,
  tool restrictions and the remaining limits.

## The data layer

The main modules in `lib/bromigos_homelab/`:

| Module | What it does |
|---|---|
| `registry.py` | the capabilities, the `Adapter` base class and `register`, and loading plugins |
| `config.py` | reads `homelab.toml` and resolves references |
| `caps.py` | the capability accessors, such as `H.hosts()`, and each record's schema |
| `snapshot.py` | builds the whole-lab snapshot from the capabilities |
| `adapters/` | bromigOS's adapters, one file per family |
| `console.py`, `cards.py` | the lab console's status cards |
| `doctor.py` | the lab console's checks |
| `jobs.py`, `jobqueue.py` | the job kinds, and the queue `bromigos-lab.service` runs |
| `labmodels.py` | what's installed and loaded on the lab's servers; load and unload |
| `catalog*.py` | the model catalog: picking, planning, serving, upgrades, the refresh and the bench |
| `provision.py`, `agentprovision.py` | generate a lab repository, apply its reviewed plan and check service health |
| `mediatui.py` | The media library and den Channels tab, with shared lab keys and safe quit |
| `tvchannels.py` | Loads the shared den channel library from bromigos-core |
| `vmproviders.py`, `vmhost.py` | owned VM lifecycle through Proxmox HTTPS or local and SSH libvirt |
| `infrastructure.py` | multi-node plans, storage inventory, approved growth and worker draining |
| `observability.py` | required monitoring, dashboards, alerts and read-only connections |
| `maintenance.py` | saved shutdown and startup plans, step confirmations and resumable run journals |
| `tui.py` | the `bromigos lab` dashboard, built with Textual |
| `tuiux.py` | shared keyboard dialogs, help and guards against background shortcuts |

The media library shows **Add to channel… (c)** below each title tab. Select a title
or album, use the button or `c`, choose **Add to** a picked channel, then **Apply channel choice**.
The button preserves the selected Music album when it opens the picker. The selected
row’s channel names stay visible beside it; hovering over a row shows the same names.
The picker lists current memberships and marks **Already in** entries for removal.

The media library’s tab bar uses `Left`/`Right` or `h`/`l` to select a tab.
`Down`/`j` enters its table; `Up`/`k` at the first row returns to the tab bar.
The Search tab (`7` or `Ctrl+F`) finds titles beyond your library. Type a title, choose
a media type, then press Enter or Search. Enter a result to request it. `/` filters
the titles you already track.
Delete shows what will go, then asks for Delete or Cancel. Cancel is selected first.
Request forms preview automatically when options change. Request stays disabled
until the current plan is ready, then locks the form until the confirmed request
finishes. Errors stay in the form.

In the delete dialog, `Left`/`Right` chooses Cancel or Delete; Enter activates
the selected button. `Up`/`Down` moves to or from the exclusion checkbox; Enter
or Space toggles it. `Tab` and `Shift+Tab` also move through controls.
Escape or `Ctrl+C` cancels. Cancel is selected when the dialog opens.

Media and Lab keep background actions and tabs inactive while a dialog is open.
Letters such as `q` remain available in inputs. Job cancellation asks first, with
**Keep job** focused. Their action buttons and footer follow the active tab; `?` opens
keyboard help. Focused controls use a highlighted border.

Download totals count each client transfer once, even when Sonarr lists every episode
of a season pack. Client size, remaining bytes and speed take precedence over stale
queue values. Paused, stalled and waiting-for-details torrents keep those states.

## Run the tests

From the repository's root:

```bash
PYTHONPATH=homelab/lib python -m unittest discover -s homelab/tests
```

The tests run against recorded API answers in `tests/fixtures/` and a stand-in lab in
`tests/labfake.py`. They need no homelab. The package's `check()` runs them on every build.

`tests/e2e_lab.py` is different: it runs against a real lab, under `dbus-run-session`.
[docs/lab.md](../docs/lab.md#tests) describes it.

`test/vm/lab-agents-e2e.py` provisions real Hermes and OpenClaw containers in a throwaway
Debian guest against an isolated model stub. It checks replies, tool restrictions,
repeat apply and the doctor, then removes the guest. It needs no lab or messaging bots.

`test/vm/lab-infrastructure-e2e.py` tests both monitoring deployments and a nested
libvirt cluster. It creates two VMs, joins a third, checks dashboards and alert delivery,
then removes the guests. It requires nested KVM and uses no real Proxmox or NAS.
[Infrastructure notes](../docs/lab-infrastructure.md) cover providers and permissions.

## Den TV controls

The den screens have a hover menu for channels, sound, volume, full screen and the guide.
The hover menu is on by default and uses `tv.hover_hint`.
`bromigos-live tv hint on|off` changes it.
The MEDIA widget has a rotary dial and per-screen sound controls. Full-screen playback
loads only the den's own `live/tvosc.lua`, with a private palette and IPC connection;
it leaves global mpv settings alone. The number-pad remote selects a screen with
Super+KP 1/2/3 and releases it with Super+KP 0, Escape or a fifteen-second timeout.

`lib/bromigos_tvplay.py` shares media search and on-demand playback between the Den TV
app, media TUI, CLI and VECTOR. `lib/bromigos_tvremote.py` shares hint, selection and
remote commands. The media TUI uses `p` to play on a den screen and `P` for a profile.

## Standalone package and AUR tests

`bromigos-lab` owns the library, commands, job services and default data at the existing
paths. It includes a fallback model catalog in `/usr/share/bromigos-lab/models.toml`.
The desktop's separately updated catalog keeps priority. The package also includes
the public verification key for signed refreshes. `bromigos-homelab` owns the
panels, decks, VECTOR plugins, launcher entries and rack hologram.

See [the package split](../docs/lab-package.md) for the clean Arch test and release gate.
No test needs desktop sudo, a window, a real lab or a real bot.
