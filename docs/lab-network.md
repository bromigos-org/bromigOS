# The lab network: bromigos lab network

`bromigos lab network` gives a lab its own private network. The lab runs Headscale, an
open-source Tailscale control server. Machines and phones join with the ordinary Tailscale
clients, with no Tailscale account. This page explains how it's built, for someone extending
it, or wiring it into the installer, Field Kit or BRODEC. For using it, read the manual's
[Your lab's private network](../manual/src/lab-network.md).

## The parts

| File | What it does |
|---|---|
| `homelab/lib/bromigos_homelab/labnet.py` | The lab's side: the reviewed plan, apply, and the verbs (`join`, `status`, `approve`, `remove`, `rotate`) |
| `homelab/lib/bromigos_homelab/reach.py` | A machine's side: the four **Reach it from anywhere** choices, the join bundle, joining now, and staging a join into a system being installed. Standard library only |
| `homelab/lib/bromigos_homelab/tui.py` | The lab console's NETWORK tab: `AddMachine`, `JoinCode`, `ApproveDevice`, `RemoveDevice` |
| `homelab/bin/bromigos-lab` | `network` hands over to `labnet.main` |
| `homelab/charts/brodec-lab/` | `network.loginServer` becomes `BRODEC_LAB_NETWORK_URL`, so the lab's bridge can tell BRODEC the address |

## Setup: a reviewed plan

`setup` follows the same model as [provisioning](lab-provision.md). `options()` checks every
answer and refuses unclear ones in plain words. `plan()` is a pure function that returns the
files, the numbered steps, the ports and the notes. `review()` prints the plan, including the
full text of every new or changed file. `write_files()` writes the plan into the lab
repository's `network/` folder. It refuses when that folder has uncommitted changes. Apply
runs only after an exact `yes`, or `--yes`.

| `--on` | Where Headscale runs | How apply reaches it |
|---|---|---|
| `quadlet` | A Podman Quadlet on one machine (`--node user@host`) | SSH, with `sudo -n`. Files go through stdin to `install` |
| `k3s` | A generated Helm chart, namespace `lab-network` | `helm` from the desktop with `--kubeconfig` and `--context`, or on a k3s box over SSH |
| `dev` | A local Docker or Podman container | The engine on this machine. Same settings, policy and container limits as the Quadlet |

| `--endpoint` | `server_url` | TLS |
|---|---|---|
| `relay` | `https://DOMAIN`. Headscale runs on the relay itself (Quadlet only) | Headscale's own Let's Encrypt, TLS-ALPN-01 on port 443 |
| `router` | `https://DOMAIN`, through one forwarded TCP 443 | The same |
| `lan` | `http://LAN-ADDRESS:8080`, published only on that address | None |

There is no Cloudflare Tunnel option. Cloudflare's proxy refuses the Tailscale control
protocol's POST upgrade. We tested this on 2026-10-30 with an account-free quick tunnel in
front of Headscale 0.29.7 and Tailscale 1.104.4. The `/key` request answered, and every
registration returned `400 Bad Request`. Headscale's own reverse-proxy documentation says
the same.

The Headscale image is pinned (`IMAGE` in `labnet.py`). Its settings have no secrets. An
identity provider's client secret is read from `--oidc-secret-file` at apply. It reaches the
machine as a root-only file, or a Kubernetes Secret, and never enters the repository.

After apply, `save_connection()` writes a marked `[network]` block into `homelab.toml`:

```toml
# Your lab's private network (bromigos lab network setup writes this block)
[network]
login_server = "https://net.example.org"
name = "Your lab's network"
plan = "/path/to/your-lab-repo/network/network.json"
join_bundle = "bromigos-net:1:…"   # only after join --stick
# end of the lab network block
```

`connection()` reads it back. `network.json` holds the target, but no secrets.

## Adapters: where Headscale's command runs

`Control` runs `headscale … -o json` wherever Headscale is:

| Target kind | Command prefix |
|---|---|
| `ssh` | `ssh … 'sudo -n podman exec -i headscale headscale …'`, as one remote command line |
| `kubectl` | `kubectl --kubeconfig … --context … -n lab-network exec -i deploy/headscale -- headscale` |
| `k3s-ssh` | `ssh … 'sudo -n k3s kubectl -n lab-network exec -i deploy/headscale -- headscale …'` |
| `dev` | `docker exec -i CONTAINER headscale` |

`devices()` and `codes()` turn Headscale's JSON into the console's records. They accept both
protobuf timestamps (`{"seconds": …}`) and RFC 3339 strings.

| Verb | Headscale command |
|---|---|
| `join --tag server` | `preauthkeys create --tags tag:server --expiration 24h` |
| `status` | `nodes list` and `preauthkeys list` (used and expired codes left out) |
| `approve CODE` | `auth register --auth-id CODE --user OWNER` |
| `remove NAME` | `nodes delete --identifier ID --force`, after the name is typed |
| `rotate` | `preauthkeys expire --id ID` for every unused code |
| `rotate --device NAME` | `nodes expire --identifier ID` |

## The join bundle

A join bundle is `bromigos-net:1:` followed by URL-safe base64, without padding, of compact
JSON:

```json
{"v": 1, "server": "https://net.example.org", "key": "hskey-auth-…", "name": "Home",
 "tags": ["tag:server"], "expires": "2026-10-31T12:00:00Z"}
```

`reach.decode()` also accepts the command `join` prints, `tailscale up --login-server URL
--auth-key KEY`. It refuses these in plain words:

- a server that isn't HTTPS, unless it's on a private address;
- a server address with a user name, password, query or fragment;
- a key that's too short;
- a newer bundle version;
- an expired code.

`reach.find_bundles()` looks in these places, in order:

1. `$BROMIGOS_REACH_BUNDLE`.
2. BRODEC pairing's drop file, `/run/bromigos/network-join`.
3. The user's `homelab.toml`.
4. The Field Kit stick's lab connection, `/root/.config/bromigos/homelab.toml`.
5. The stick's folder itself.

The stick carries `homelab.toml` already ([fieldkit.md](fieldkit.md)), so a bundle saved with
`join --stick` travels without changes to Field Kit.

## Joining a machine

`reach.join_now()` starts `tailscaled` if it isn't running, then runs:

```text
tailscale up --reset --login-server=URL --auth-key=file:KEYFILE \
  --accept-routes=false --exit-node= --advertise-exit-node=false --advertise-routes= [--hostname=NAME]
```

The key is in a 0600 temporary file, removed afterwards. It never appears on a command line.
As root it runs directly. Otherwise it uses `sudo` in a terminal and `pkexec` elsewhere.
`$BROMIGOS_TAILSCALE` replaces the `tailscale` command. The tests use this to point it at a
container or a stand-in. A machine already on another network needs `--force`, which adds
`--force-reauth`.

## For the installer and bromigOS Server's setup

The installer imports `bromigos_homelab.reach`. `bromigos-lab` is on both media.

- `reach.CHOICES` is the step's four answers, in order. Each has an `id`, a `title`, `words`
  and `packages`, and an `account` when it needs one. `brodec` is first and the default.
- Before **Install**, `reach.decode(text)` checks a pasted bundle, and `reach.check_wireguard(text)`
  checks a WireGuard configuration. `reach.find_bundles()` offers a bundle the machine already has.
- The install adds `CHOICE[mode]["packages"]` to the package list.
- After the system is copied, call `reach.stage(root, answer, hostname)`. From a shell, run
  `python3 -m bromigos_homelab.reach stage --root /mnt --answer FILE --json`.

`stage()` writes this into the new system:

| Choice | Files | Enabled |
|---|---|---|
| `lab-network` | `/etc/bromigos/reach/authkey` (0600) and `bromigos-reach-join.service` | `tailscaled.service` and the join unit |
| `wireguard` | `/etc/wireguard/wg0.conf` (0600) | `wg-quick@wg0.service` |
| `tailscale` | With an auth key: the key and the join unit, without `--login-server` | `tailscaled.service` |
| `brodec` | nothing more | nothing |

Every choice also writes `/etc/bromigos/reach.json`, which records the choice without the key.
The join unit runs once at first start. It deletes the key afterwards, whether or not the
join worked.

On a running machine, `reach.apply(answer)` does the same thing now. `bromigos lab network
reach` asks the question in a terminal (`reach.choose()`). That's what Field Kit's
**Server › Network** runs.

## BRODEC

The lab's bridge reports the network's address in the lab report. The chart sets
`BRODEC_LAB_NETWORK_URL` from `network.loginServer`. The phone shows **Connect this phone to
my lab network** in LAB only for the account's own lab, and only from a verified report. It
gives the steps for the Tailscale app's custom control server, with the address to copy. The
Tailscale apps have no documented link that sets a custom server, so BRODEC doesn't use one.

## Tests

| Test | What it covers |
|---|---|
| `homelab/tests/test_labnet.py` | Every plan (Quadlet relay, LAN, k3s router with an identity provider), refusals, the policy, the chart with `helm lint` and `helm template`, records from Headscale's recorded answers (`tests/fixtures/labnet/`), each verb's commands, `homelab.toml`'s block |
| `homelab/tests/test_reach.py` | The bundle, joining with a stand-in `tailscale`, the installer step against a stand-in installer staging into a fake root, the terminal question |
| `homelab/tests/test_labnet_tui.py` | The NETWORK tab with Textual's pilot: members, Add (code and QR), Approve, Remove with Keep focused |
| `homelab/tests/e2e_labnet.py` | Real Headscale 0.29.7 and Tailscale clients in containers (below). Not in the package check, because it pulls images and runs privileged containers. Run it with `PYTHONPATH=lib:../lib:tests python -m unittest e2e_labnet` from `homelab/` |

The end-to-end test has three parts:

- **dev:** `setup --on dev`, three joins, reachability under the default-deny policy, a used
  code refused, then remove and rotate.
- **Quadlet:** `setup --on quadlet` over SSH to a lab machine in a container
  (`tests/labnet-node/`, with systemd, Podman and sudo). A client joins, and its device
  survives a restart of the service.
- **k3s:** `setup --on k3s` with the Helm chart on a real k3s (`docker.io/rancher/k3s`). The
  service answers on the node's own address, and a client joins.

`BROMIGOS_E2E_NODES=0` skips the Quadlet and k3s parts. The tests can't cover Let's Encrypt
on a public domain (`relay` and `router`) or a real identity provider. Their plans are checked,
and Headscale's `configtest` reads the settings they make.
