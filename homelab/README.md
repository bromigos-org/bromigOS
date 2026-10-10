# homelab/: the homelab integrations

This folder is the `bromigos-homelab` package. It connects the servers someone runs at home
to the bromigOS desktop. One data layer asks for *capabilities*, kinds of readings such as
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
| `bin/` | `/usr/lib/bromigos/bin/` | `bromigos homelab`, `bromigos setup homelab` and `bromigos lab` |
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
| `mediatui.py` | the media library, with shared lab table keys and safe quit from forms |
| `tui.py` | the `bromigos lab` dashboard, built with Textual |

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
