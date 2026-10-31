# VECTOR in Field Kit

VECTOR is bromigOS's AI assistant. On the desktop he lives on the screen as a hologram. In
[Field Kit](fieldkit.md) and on [bromigOS Server](server.md)'s console he's a chat in the
terminal: `bromigos fieldkit` › VECTOR. He sees what Field Kit sees, he explains it in plain
words, and he proposes Field Kit's own repairs. Nothing he proposes runs until the person at the
machine approves it on the screen.

This page is for contributors.

## What existed, and what this adds

From the vector repository (`bromigos-org/vector`), read, not copied:

- **His persona**, `holo/vector/persona.py` (`persona.build()`). On a machine where the vector
  package is installed, Field Kit uses its own prompt, the identity half (everything before
  "HOW YOU WORK", which is about the desktop's tools). Field Kit and Server don't have the
  package (it needs Hyprland), so `vector_tools.py` carries a short summary of the same "WHO YOU
  ARE" and "PERSONALITY" sections, and says where it came from. He isn't given a new
  personality.
- **His hard limits**, from the same prompt and `docs/safety.md`: never money, never secrets,
  and the operator's kill switch.
- **The kill switch**, `holo/vector/switch.py`: markers in
  `~/.local/state/bromigos/vector-switch/off`, `$XDG_RUNTIME_DIR/bromigos-vector-switch/off`
  and the old `~/.local/state/bromigos/vector-shell-off`. Any one present means off: he can
  talk and look things up, but runs nothing.
- **His brain's wiring**, `holo/vector/llm.py`: one OpenAI-compatible endpoint
  (`vector.toml [llm] base_url`, targets.toml, a local Ollama).

There is no headless or terminal client in the vector repository. `bromigos-holo ask` sends a
question to the desktop's running hologram over its socket, so it needs the desktop.

BRODEC's lab bridge (`brodec-lab`, `packaging/prebuilt/brodec-lab/`) lets VECTOR answer about a
lab from the BRODEC app, with its own brain (`BRODEC_BRAIN_URL`). BRODEC's machine jobs
(`brodec-machine`, its `docs/MACHINE_JOBS.md`) pair a machine, keep its encrypted room and stream
Herdr to the phone: Field Kit pairs through it ("Pair with BRODEC", below).

What this adds:

| File | What it is |
|---|---|
| `core/crates/bromigos/src/fieldkit_vector.rs` | The screen: ratatui, bromigos-tui's DRIFTGLASS widgets |
| `fieldkit/lib/bromigos_fieldkit/vector_tools.py` | The engine's `vector` verb: his brain, what he sees, proposals, approvals, the audit log |
| `fieldkit/tests/test_vector_tools.py` | Tests against a stand-in OpenAI-compatible server on localhost |
| `core/crates/bromigos/src/fieldkit_vector/pair.rs` | PAIR WITH BRODEC: the agent's code as a QR, starting it, enrolling a phone |
| `fieldkit/lib/bromigos_fieldkit/machine_link.py` | BRODEC's agent's state from its own files, Field Kit's capability file, the phone's controls |
| `fieldkit/tests/test_machine_link.py` | Its tests, with stand-ins for the agent and systemd |

## The screen

Three columns where there's room, after the operator's mock-up:

- **His presence**, on the left. The orb is a braille hologram with a scan arc going round and a
  pulsing core. It is the screen's one FLARE, and it holds still under reduced motion. Below it
  are "V E C T O R" and his state: *here*, *thinking*, *waiting for you*, *applying the plan*,
  *done · restart to check it*, or *emergency switch on · only talks*. Then three chips:
  - his brain, for example *lab · node-a*, or *none · findings only*;
  - BRODEC: *paired* or *not paired*;
  - the internet: *no internet used* when his brain is on this machine or the local network, or
    when there's no brain at all. Otherwise it says *uses the internet*.
- **He's looking at**: what goes to his brain with each question. The chips are the last boot's
  log, the mounted install, the repair findings, and any file or disk the person adds.
  - Space turns a chip on or off.
  - "+ add a file or disk" (or `/add PATH`) adds one. The engine refuses secrets, and reads at
    most the last 64 KB of a file.
  - `x` removes an added one.
- **The conversation**, in the middle.
  - The person's messages are on the right with a cyan edge; his are on the left with a phosphor
    edge.
  - Under his name, a faint *looked at: …* line lists what he really read for that answer: the
    context that was on, and the checks he ran.
  - The view scrolls with PgUp/PgDn and the wheel. *↑ more* and *↓ more* sit on the panel's frame,
    never over the text, and a resize keeps the place.
- **The PLAN card**: what he proposed in one answer, as steps.
  - Each step has a checkbox. The card shows the risk (low for backed-up fixes; medium for a
    rollback, the boot menu, the boot options or a restart; high for a command, a power-off or an
    update) and what is true about backups. See "What he can do".
  - The exact changes show from the start; **d** hides them.
  - **Apply** (`a`, or Enter) runs the steps in order, through the same approval as before. A
    step that needs a typed word or a passphrase still opens that dialog. Esc there stops the
    plan, and nothing after that step runs.
  - **Not now** (`n`) runs nothing, and tells the engine each step was declined.
  - When BRODEC is paired, the card also says it's waiting on the phone.
  - Afterwards the steps tick (✓). The card then offers **Restart now** (a reboot proposal, approved
    by typing `reboot`) and **Undo**.
- **Undo** asks the engine for an undo proposal for each step that left backups. They come back
  as their own card, to Apply or not.
  - Undo copies every file in the step's backup folders back to its own path. The backups stay
    where they are. A file the step newly created stays.
  - A rollback has no file backup. The system it replaced is kept beside it, and Repair › Roll
    back to a snapshot can return to it.
- **The composer**: *Ask* or *Fix* (Shift+Tab). In Fix, he checks, explains and proposes every
  step of the fix at once.
  - Typing `/` lists the commands: `/look`, `/add PATH`, `/fix`, `/ask`, `/pair`, `/clear`,
    `/rules`, `/help`.
  - `?` (with nothing typed) opens his rules and the keys.
- **Try asking** and **His rules**, on the right.
  - The questions come only from what Field Kit detected: findings that aren't fine, disks with
    SMART, a USB drive beside a mounted install, snapshots, BitLocker, Windows, a Server or live
    medium. Enter asks one.
  - The rules: asks before every change, shows the exact edit first, backs up and can undo,
    never money, never secrets, never touches the emergency switch.

Tab moves between the composer, the plan, what he's looking at and the questions. Ctrl+P (or
`/pair`) pairs with BRODEC. On the plan, `c` shows its exact commands: each step's change, as
the engine saved it (`vector pending`), which is the copy that runs; `y` copies them. Alt+X
opens a shell from anywhere on the screen, as in the rest of Field Kit; exiting it comes back
to VECTOR as it was. Other Alt keys are Field Kit's section keys and aren't typed.

### Every size

It uses `bromigos_tui::layout`, and lays itself out again on every frame:

| Width | Layout |
|---|---|
| Wide, 150 and more | The three columns above. |
| Medium, 110–149 | No right column. The questions become chips above the composer, and the rules move under `?`. |
| Narrow, 80–109 | One column. A small orb sits beside his name, state and chips. What he's looking at fits on one chip line. The conversation is full width. |
| Tiny, under 80 | No orb, and the chips are icons only. The plan card's buttons are stacked. |
| Under 40×15 | "Make the window bigger". |

On the Linux console it uses the console's 16 colours. Its orb is a ring of plain characters with
the same scan and core. With `BROMIGOS_ASCII` the screen is plain ASCII, his words and the
engine's labels included.

## What he sees

The engine gives him, at each turn, what Field Kit itself knows:

- the overview: this computer, what's on its drives, the network, the suggestions;
- the install Field Kit works on, if one is mounted;
- the last boot's findings and the black screen checks, with each finding's fix;
- the snapshots.

He can also call three read-only tools during a turn: `check` (black-screen or last-boot),
`snapshots` and `disks`. They change nothing, so they run without asking.

## What he can do

Field Kit's own actions, each as a proposal:

| Tool | The change shown | How it's approved |
|---|---|---|
| `fix` | The finding, its explanation and its fix (which keeps a backup) | Apply on the plan card |
| `rollback` | The snapshot the install will start from, and that the current system is kept | Typing `rollback` |
| `grub_repair` | What's reinstalled and remade (backed up) | Apply |
| `boot_options` | A diff of `GRUB_CMDLINE_LINUX_DEFAULT` (backed up) | Apply |
| `mount` | The device and where it's mounted | Typing the disk's passphrase |
| `unmount` | Unmount and lock | Apply |
| `run_command` | The exact command and why | Typing `run` |
| `undo` | The files it puts back, from which backup folders | Apply |
| `control` | Restart (`reboot`), power off (`poweroff`), update a Server (`update`) | Typing the word |

A proposal is saved, with its exact change, in `/run/bromigos-fieldkit/vector/approvals/<id>.json`
(mode 600). It runs only when the person approves it on the screen
(`fieldkit-engine engine vector run ID --by local`). The switch is checked again right before it
runs. Each proposal runs once. Declining runs nothing.

`run_command` is refused outright when the command touches money (payments, wallets, trading),
secrets (Vault, keys, tokens, SSH keys, `/etc/shadow`, the keyring) or his kill switch. His
other tools can't reach those either.

Every proposal, approval, refusal and result goes to the audit log,
`/var/log/bromigos-fieldkit-vector.log`.

### The kill switch

The switch is the operator's (vector repo, `switch.py`). Field Kit checks the same markers, for
root, the sudo caller, every person on this system and every person on the install Field Kit
has mounted. While any one is there, the top bar says *EMERGENCY SWITCH ON · he only talks* (in the warning colour; otherwise *emergency switch: off · he can act*), his state says *emergency switch on · only talks*, he's told so, his proposals
are refused, and `run` refuses anything waiting. Field Kit never writes or removes the markers.

## His brain

No model is on the stick: it would be too big. The engine tries these in order and uses the
first that answers `/v1/models`:

1. `BROMIGOS_FIELDKIT_BRAIN_URL` (with `_MODEL` and `_KEY_FILE`), for a test or by hand.
2. **The lab's model over the local network**: `homelab.toml`'s `litellm`, then `openai` and
   `ollama` sources (the stick's `fieldkit/homelab.toml` is copied to root's
   `~/.config/bromigos/homelab.toml` at boot). The key is the source's `auth_ref`, resolved the
   way bromigos-lab resolves it. No internet is needed.
3. **The server's lab bridge**: `/etc/brodec-lab/brodec-lab.env`'s `BRODEC_BRAIN_URL`,
   `BRODEC_BRAIN_MODEL` and `BRODEC_BRAIN_KEY_FILE`.
4. **VECTOR's configured service**: `vector.toml [llm] base_url` (the user's or `/etc`'s), with
   its `api_key_file`.

The model is the source's own when it names one, else the first the endpoint lists. The key
never leaves the engine: the screen sees the source, the URL and the model only.

**No brain.** The section still works. He reads out Field Kit's own findings (each with its
explanation and the Repair item that fixes it) and says how to give him a brain: connect to the
lab (Lab › Network settings) with the lab's connection on the stick, or a server's lab bridge.

## From a phone

### Pair with BRODEC

BRODEC already has what pairing a machine needs (its `docs/MACHINE_JOBS.md`): `brodec-machine`,
BRODEC's agent on a machine, pairs it with the owner's account through the platform's
`brodecLabPair` (`kind: "machine"`) and the account system's device flow, keeps an end-to-end
encrypted machine room, enforces the owner and fingerprint rules (look, everyday, serious,
never remote), runs STOP ALL, keeps a hash-chained audit log, and streams Herdr panes to the
phone (the remote terminal). Field Kit reuses all of it and reimplements none of it.

**On the screen.** VECTOR › CTRL+P, or the Server section (`crate::fieldkit_vector::pair(&look,
engine)`), opens PAIR WITH BRODEC; so does Server › Pair with BRODEC. bromigOS Server's
first-boot tour (`bromigos welcome-console`) pairs too, in its "Pair your phone" step.

- Not paired: P starts BRODEC's agent, after the person approves (the proposal `pair_start`). With
  no `/etc/brodec-machine/machine.toml` yet, Field Kit writes its own (root's, 0644, here at the
  machine; an existing one is the operator's and stays):
  - no jobs, no NEW SESSION, no den;
  - the remote terminal for Herdr's `fieldkit` workspace, and the phone's own shells
    (`phone_shells = true`);
  - machine controls (`[system] enabled = true`): restart and shut down on a stick, update too
    on bromigOS Server.

  On a stick the agent runs as root (`systemd-run`, unit `brodec-machine-fieldkit`); on an
  install, the user's `brodec-machine` service.
- Waiting: the agent's pairing code as a QR, with the code to type (`KPGG-ZFVT`). Dark on
  light with both colours set in every cell: a cell that is all dark or all light is a space on
  that colour, and only a cell split between two modules draws a half block, so no font's block
  that falls short of its cell leaves a seam between rows. The standard's four-module quiet zone,
  error correction M; each module takes
  1 to 3 cells, the most that fit, so it scans on a 1080p and a 4K console. The `qrcode` crate
  is the one BRODEC uses (0.14.1, MIT or Apache-2.0).
- Paired: the name BRODEC gave it. When the phone asks (this machine › ALLOW THIS PHONE), E runs
  `brodec-machine enroll`: BRODEC's own enrolment, which shows the phone's key to compare. On
  Field Kit's root console it runs as is; anywhere else through polkit (`pkexec`), never a
  command to type.

**Where the state comes from.** BRODEC's own setup-screen command (its `docs/MACHINE_JOBS.md`,
"Pairing from a setup screen"):

- `brodec-machine pair --json --once`, as the agent's user, is what the engine's `vector pair`
  reads. Its last event says where pairing is: `code` (with `qr`, `qr_text`,
  `user_code_display`), `waiting`, `paired`, `failed` (`no_capability_file`, …).
- An older agent without the command: its own files (`pair-code.json`, `pairing.json`).
- The welcome tours' "Pair your phone" step (`lib/bromigos_firstrun.py`) keeps
  `brodec-machine pair --json --start` running while it's open and closes it with SIGTERM: only
  the watching stops, the code keeps working. The exit codes are 0 paired, 1 failed or timed
  out, and 130 cancelled. On bromigOS Server and a Field Kit stick, the root file it writes
  first is Field Kit's (`fieldkit-engine brodec-setup`); elsewhere the package's example. After
  `paired` it offers "Allow this phone" (`brodec-machine enroll`, with sudo).
- A lab's VECTOR bridge pairs the same way with `sudo brodec-lab pair --json`.

`bromigos fieldkit qr TEXT` draws any text with the same widget, full screen. Field Kit's CI
test decodes it with zbarimg from kmscon and from the bare kernel console
(`iso/fieldkit/ci-test.sh`).

The engine's verbs: `vector pair` (the state above), `vector pair-start` (the proposal),
`vector controls`, `vector control ACTION`. `fieldkit-engine brodec-setup` is root's file alone.

### What the phone may do here

The phone's **Restart**, **Shut down** and **Update bromigOS** are BRODEC's own machine controls
(its `docs/MACHINE_JOBS.md`, "Machine controls"):

- The agent checks the phone's fingerprint and `[system]` in root's file.
- A fixed system unit acts.
- A restart counts down 30 seconds and can be cancelled from the phone.
- On Server, the update is `bromigos-server update --now`, with its snapshot, health check and
  rollback.
- A Field Kit stick never updates itself.

Field Kit doesn't queue these a second time: `vector controls` names BRODEC as the phone's path
for each.

Field Kit's own approvals (the queue: here, or one day from BRODEC) are for what VECTOR proposes:

| VECTOR's control | On Field Kit and Server | Confirmed by typing |
|---|---|---|
| Restart | `systemctl reboot` (a mounted install is unmounted first) | `reboot` |
| Shut down | `systemctl poweroff` (the same) | `poweroff` |
| Update bromigOS | bromigOS Server: `bromigos-server update --now`. A stick: refused, "a Field Kit stick doesn't update itself" | `update` |
| New terminal tab | `herdr tab create --label "Field Kit shell"`, else a tmux window in the `fieldkit` session | |
| Run a command | `run_command`: the exact command shown, refused for money, secrets and the kill switch | `run` |

### Herdr, now

Remote help ([fieldkit.md](fieldkit.md#remote-help)) turns SSH on and runs the menu in a tmux
session called `fieldkit`. From a phone or a laptop:

```bash
ssh root@ADDRESS            # then: tmux attach -t fieldkit, the same screen, VECTOR included
herdr --remote root@ADDRESS # a Herdr workspace on the machine: panes, live view, keys
```

Once paired, BRODEC's remote terminal shows the `fieldkit` workspace's panes on the phone the
same way, signed by the enrolled phone.

### What's still to build

**On the medium and on Server: the `brodec-machine` package.** BRODEC splits its PKGBUILD into
`brodec-desktop` and a GTK-free `brodec-machine`, staged at `refs/brodec-machine/package`. This
repository publishes it with `.github/workflows/brodec-machine.yml` (`packaging/ci/brodec-machine.sh`,
the desktop package's checks for `brodec-machine`). Until that first publish:

- the Field Kit stick lists it `if_available` (`iso/fieldkit/packages.toml`): a build leaves it
  out while no repository has it, and every stick built after has it;
- `bromigos-server` offers it in `optdepends`, and moves it to `depends` once it's published.

[packaging/README.md](../packaging/README.md#brodecs-machine-agent) has the order.

**In BRODEC (app, protocol and agent), for VECTOR's approvals and chat in the app.** Field Kit's
side is ready: the queue and its verbs. BRODEC's machine room would carry, following its own
rules:

- `machine.hello`: a `fieldkit` block, the controls (`vector controls`) and the switch;
- `fieldkit.pending` (machine → owner): the queue (`vector pending`), each with its `title`,
  `change`, `confirm` word and `needs` (`passphrase` never leaves the machine: such a proposal
  is answered only at the machine);
- `fieldkit.answer` (owner → machine): `id`, `approve` or `deny`, the typed `confirm` word, and
  `auth` signed by the phone's hardware job key (serious, a fingerprint per use). The agent
  checks it as any request, then runs `fieldkit-engine engine vector decide ID approve --by
  DEVICE` and `run ID --by DEVICE`;
- `machine.control` (owner → machine): `action`, `auth` (serious): the agent runs `vector
  control ACTION`, then the same decide and run;
- `fieldkit.ask` and `fieldkit.reply` (the chat): the agent relays the owner's words to `vector
  ask` and his reply back, proposals included. VECTOR's line stays the machine's, never the lab
  bridge's (BRODEC's rule: VECTOR never dispatches);
- STOP ALL also switches Field Kit's VECTOR off (his kill switch's markers), as the phone's sheet
  already offers for the desktop's.

## Tests

```bash
PYTHONPATH=fieldkit/lib python -m unittest discover -s fieldkit/tests -p 'test_vector_tools.py'
PYTHONPATH=fieldkit/lib python -m unittest discover -s fieldkit/tests -p 'test_machine_link.py' 
cd core && cargo test -p bromigos fieldkit_vector
```

- `test_vector_tools.py`: the brain's order (the lab, then the bridge, then VECTOR's own); a turn
  against a stand-in OpenAI-compatible server that reads a check, proposes a fix and a forbidden
  command (the command is refused, the fix waits and runs only after approval, once); the kill
  switch refusing; the hard limits; a phone's decision recorded without running; no-brain mode;
  the embedded persona naming its source; what he looked at, Fix mode and the context toggles
  (an added file read, secrets refused); the LAN check; Undo putting back what a fix moved out;
  the questions coming only from findings.
- `fieldkit_vector/tests.rs` tests the screen against a stand-in engine:
  - every size: 200×55, 150×45, 120×35, 80×24, 60×30 and 40×15, each with whole rows, the
    conversation's frame unbroken, and the right columns per breakpoint;
  - stacked buttons on a Tiny screen;
  - scrolling, and the place kept across a resize;
  - no-brain mode;
  - a plan:
    - nothing runs before Apply;
    - Not now declines both steps;
    - Fix mode, then Apply runs both in order, once;
    - Undo comes back as its own plan;
  - Restart only after typing `reboot`;
  - a rollback's typed word, and Esc stopping a plan;
  - the commands;
  - what he's looking at, as sent;
  - reduced motion holding the orb still;
  - the console and ASCII looks (all ASCII, frame whole).

  Captures: `tui-vector.txt` (no brain), `tui-vector-approval.txt`, `tui-vector-applied.txt`,
  `tui-vector-console.txt`, and `tui-vector-150.txt`, `-110`, `-80` and `-60`.
- `bromigos-tui/src/orb.rs`: the scan moves and the core breathes. The same time draws the same
  orb. The plain ring is ASCII.
- `fieldkit_vector/pair.rs`: the QR's quiet zone and module size for the screen, the code as
  BRODEC shows it, the waiting screen with the QR and the code (`tui-vector-pair.txt`; decoded
  back to its URL with zbarimg), and starting the agent only after approval.
- `test_machine_link.py`: the agent's states from its own files, the capability file, pairing
  starting only once approved, and the phone's controls (update refused on a stick).
