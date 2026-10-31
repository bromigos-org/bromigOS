# Your lab's private network

Reach your machines from anywhere, privately. Your lab can run its own private network. Your
laptop, your phone, your servers and your lab machines join it. Then they reach each other
from anywhere, as if they were all at home, and nobody else can reach them.

Your lab runs the network itself, with an open-source server called Headscale. Devices use
the ordinary Tailscale apps to join, but you don't need a Tailscale account. The apps talk
only to your lab.

You don't need this to use BRODEC. BRODEC already reaches your machines on its own,
end-to-end encrypted. The lab network is for everything else: SSH to a server, a web page on
your lab, a file share, from wherever you are.

## Set it up

You need a lab with at least one machine (see [Setting up a lab](lab.md#setting-up-a-lab)).
Then run one command. It shows you exactly what it will make and do, and changes nothing
until you type `yes`.

Choose how your devices reach the network when they're away from home:

| Choice | What it needs | Good for |
|---|---|---|
| **Your relay** | A small server on the internet that you rent, and a domain name pointing at it | The most reliable choice. The network keeps working even when your home internet is down. |
| **Through your router** | One forwarded port (TCP 443) on your router, and a domain name pointing at your home. A free dynamic DNS name works | Not renting anything |
| **Your network only** | Nothing | Trying it out. Devices can only sign in while they're at home |

Then run the command for your choice, with your own names:

```bash
# Your relay: Headscale runs on the relay itself
bromigos lab network setup --on quadlet --node you@your-relay --endpoint relay --domain net.example.org

# Through your router, on a lab machine
bromigos lab network setup --on quadlet --node you@labbox --endpoint router --domain net.example.org

# Your network only
bromigos lab network setup --on quadlet --node you@labbox --endpoint lan --lan-address 192.168.1.20
```

If your lab runs Kubernetes (k3s), use `--on k3s` instead. It installs the network as a Helm
chart in its own namespace.

The plan lists the files it writes into your lab repository, prints each one in full, and
numbers every step. Read it, then type `yes`. When it's done, the lab console has a
**NETWORK** tab.

## Add a machine

Each machine joins with a one-time **join code**:

```bash
bromigos lab network join
```

It prints the code, a QR code of it, and the plain Tailscale command. A code works once, and
stops working after a day if nobody uses it. Then use the code on the new machine:

- **A machine that already runs bromigOS:** `bromigos lab network connect`, then paste the code.
  If the machine has a code from a Field Kit stick, it finds it by itself.
- **Field Kit:** **Lab › Join my lab network**. For bromigOS Server, **Server › Network**.
- **Any Linux machine with Tailscale:** run the `sudo tailscale up …` command that `join`
  printed.

To carry a code on your next Field Kit stick, make it with `bromigos lab network join --stick
--expires 7d`, then make the stick.

In the lab console, press **6** for the NETWORK tab, then **A** to add a machine. It shows the
same code and QR code.

## Connect your phone

1. Install the Tailscale app.
2. In BRODEC, open **LAB** and tap **Connect this phone to my lab network**. It shows your
   network's address, with a button to copy it, and the steps for your phone.
3. In the Tailscale app, choose your lab's server instead of Tailscale's:
   - **Android:** the settings menu, then **Accounts**, then the three dots, then **Use an
     alternate server**. Paste the address.
   - **iPhone:** the account icon, then **Log in…**, then the menu at the top, then **Use custom
     coordination server**. Paste the address.
4. The app shows a code. Approve it on your lab: in the lab console's NETWORK tab press **p**,
   or run `bromigos lab network approve CODE`. If your network signs in through your own
   identity provider, just sign in there instead.

## Who can reach what

Nothing can connect unless it's allowed. Out of the box:

- Your own devices reach each other, your lab machines and your servers.
- Lab machines reach each other and your servers.
- Servers reach nothing on their own, and nothing but you reaches your devices.

## See, remove and start again

| What | Command | In the lab console |
|---|---|---|
| Who's on it, online or when last seen | `bromigos lab network status` | the NETWORK tab |
| Take a device off | `bromigos lab network remove NAME` | **x** on its row |
| Approve a phone or laptop | `bromigos lab network approve CODE` | **p** |
| Cancel every unused join code, such as on a lost stick | `bromigos lab network rotate` | |
| Make one device sign in again | `bromigos lab network rotate --device NAME` | |

Removing asks you to type the device's name first. Every command takes `--json`.

## For power users

### What setup makes

`setup` writes everything into your lab repository, under `network/`, so you can read it,
change it and commit it:

| File | What it is |
|---|---|
| `config.yaml` | Headscale's settings. No secrets. |
| `acl.hujson` | The access policy, in HuJSON (JSON with comments) |
| `quadlet/headscale.container`, `headscale-data.volume` | The Podman Quadlet, when it runs on one machine |
| `helm/headscale/` | The Helm chart, when it runs on k3s |
| `network.json` | Your answers, so running `setup` again reuses them |

Change a file, commit it, and run `setup` again. It shows what changed before it applies.
The container runs with a read-only root filesystem and no new privileges. Its version is
pinned, so nothing updates by surprise.

### ACLs and tags

A device belongs either to a person or to a **tag**. Your phone and laptop belong to you.
Machines carry a tag instead:

- `tag:server` for servers. `join` gives this one by default.
- `tag:lab` for your lab's own machines: `join --tag lab`.

The policy names your devices through `group:owners`. To let a server reach your lab's model
server on one port, add a rule to `acl.hujson`:

```json
{"action": "accept", "src": ["tag:server"], "dst": ["tag:lab:4000"]}
```

Then run `setup` again. Headscale's [policy reference](https://headscale.net/stable/ref/policy/)
lists everything a rule can say.

### Join codes and keys

A join code is a Headscale pre-auth key, wrapped with the network's address so one paste is
enough. It starts with `bromigos-net:1:`.

- A code works once unless you pass `--reusable`.
- `--expires` sets how long it waits to be used, such as `30m`, `24h` or `7d`.
- `--ephemeral` makes a machine leave the network by itself when it goes offline. This suits a
  Field Kit stick you boot once to help someone.
- Server keys never expire. Use `rotate --device` to make a machine sign in again.

On the machine, the key goes to Tailscale in a file only root can read, never on a command
line. A machine joining from the installer deletes its key after the first start, whether
or not it worked.

Joining never makes a machine an exit node and never adds subnet routes. Its own internet
traffic still goes out its own way.

### Sign-in: your identity provider or local users

By default the network has local users: you, named with `--owner`. A phone or laptop signing
in shows a code for you to approve.

With your own identity provider, such as Authentik, Keycloak or Google, people sign in there:

```bash
bromigos lab network setup … --owner you@example.org \
  --oidc-issuer https://id.example.org/application/o/headscale \
  --oidc-client-id headscale --oidc-secret-file ~/headscale-client-secret
```

Add `https://YOUR-NETWORK/oidc/callback` as the client's redirect address. The secret is
sent to the lab machine and never written into your repository. Only the owner may sign in
until you add others to `allowed_users` or `--oidc-allowed-domains`.

### DERP: when two devices can't connect directly

Devices connect to each other directly whenever they can. When a firewall stops that, they
send their traffic through a **DERP relay**. The traffic stays end-to-end encrypted, so the
relay can't read it.

| `--derp` | Relays through |
|---|---|
| `tailscale` | Tailscale's public DERP servers. No account. The default, except on a relay |
| `embedded` | Your own, built into Headscale, and Tailscale's as a fallback. The default on a relay. Open UDP 3478 too |
| `self` | Your own only |

Your own DERP needs the network on HTTPS, so it works with a relay or a forwarded router port.

### Cloudflare Tunnel or a relay

A Cloudflare Tunnel doesn't work for this. Tailscale's apps start their connection in a way
that Cloudflare's proxy refuses. We tested it with a tunnel: every sign-in came back
`400 Bad Request`. That's why setup offers a relay or a router port instead. Both give
Headscale a direct, ordinary HTTPS connection, and Headscale gets its own Let's Encrypt
certificate.

A relay keeps working when your home internet is down, and it hides your home's address. A
router port costs nothing, but the network is only up while your home internet is.

### Reach it from anywhere: the other choices

`bromigos lab network reach` asks how a machine is reached when it isn't at home, with four
answers. **Through BRODEC only** is the default, and changes nothing. **Join my lab's private
network** takes a join code. Two more are for other setups:

- **WireGuard (advanced)** takes a WireGuard configuration you made yourself. bromigOS refuses
  one that runs commands, such as `PostUp` lines.
- **Tailscale's service** uses Tailscale's own coordination service. That needs a Tailscale
  account, and Tailscale the company coordinates your devices.
