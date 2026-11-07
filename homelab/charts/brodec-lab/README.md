# brodec-lab: BRODEC's lab bridge for Kubernetes

This chart runs BRODEC's lab bridge in your cluster. The bridge reads your lab's own
monitoring, such as Prometheus and Alertmanager, and reports what it sees to your BRODEC
account, end to end encrypted. In BRODEC, that report is VECTOR in your LAB tab. VECTOR is
BRODEC's AI assistant. Only you, and the people you share your lab with, see the reports.

It only reads. It has no Kubernetes rights, no admin rights in your lab, and none of your
passwords.

## Install it

You need BRODEC on your phone, with encrypted comms on (it's in beta), and Helm 3.8 or later.

```bash
helm install brodec-lab oci://ghcr.io/bromigos-org/charts/brodec-lab \
  -n brodec-lab --create-namespace \
  --set lab.name=basement-rack \
  --set sources.prometheusUrl=http://prometheus-operated.monitoring.svc:9090 \
  --set sources.alertmanagerUrl=http://alertmanager-operated.monitoring.svc:9093
```

Replace the names with your own:

- `lab.name` is what BRODEC calls this lab. Use letters, digits, `-` and `_`.
- `sources.prometheusUrl` and `sources.alertmanagerUrl` are your Prometheus and
  Alertmanager, as the cluster reaches them. Leave one out if you don't have it.

## Pair it with your account

The bridge waits for you when it starts. Show its pairing code:

```bash
kubectl -n brodec-lab exec deploy/brodec-lab -- brodec-lab pair
```

It prints a code and a QR code. In BRODEC, open **LAB**, choose **CONNECT YOUR LAB**, and
scan it. Check that the code on your phone matches, then confirm with your fingerprint.
A code works for 10 minutes. When it runs out, the bridge makes a new one.

The first report arrives within a minute. Each BRODEC account can own one lab during the beta.

## What it can read

| Value | What VECTOR reads |
|---|---|
| `sources.prometheusUrl` | Machines, disks, GPUs and services, from Prometheus |
| `sources.alertmanagerUrl` | The alerts firing now |
| `network.loginServer` | Your lab's private network ([lab-network](../../../manual/src/lab-network.md)), such as `https://net.example.org`. BRODEC then offers "Connect this phone to my lab network". The bridge only passes the address on. `network.name` is what BRODEC calls it |
| `sources.labApi.url` | A status page with the lab status API (`GET /api/status`). Put its read-only token in a Secret and name it in `sources.labApi.tokenSecret` |
| `brain.url`, `brain.model` | A language model in your lab, so VECTOR can answer questions. Any OpenAI-compatible API, such as Ollama, vLLM or LiteLLM, ending in `/v1`. Put its key, if it has one, in a Secret named in `brain.keySecret` |

Without a brain, VECTOR still reports. He tells you he has no brain in this lab yet.

## Guests

The people you share the lab with as **Can ask** talk to VECTOR in their own chat, and can ask
him in a group. He never answers them with `brain`, which may have your tools or your memory.
He answers them with `guestBrain`, and tells it only the lab's latest report: the one they
already see.

| Value | What it does |
|---|---|
| (unset, the default) | Guests get a polite "I can't answer questions from guests in this lab just now". They still see the lab's reports |
| `guestBrain.url`, `guestBrain.model`, `guestBrain.keySecret` | A brain for guests, as `brain` above. It must have no tools of its own: a plain model API (Ollama, vLLM, LiteLLM), not an agent |
| `guestBrain.sameAsBrain: true` | Guests use `brain` too. Only when `brain` is a plain model API with no tools of its own |

If the guest brain fails, the guest hears "I can't answer right now". VECTOR never asks `brain`
instead. `brodec-lab check` checks both brains.

You choose what he reports, and where he looks, in BRODEC: **Settings › Your lab**.

## Media server (BROADCAST)

The chart can run a media server beside the bridge, so you can go live and the people you
choose watch in BRODEC: from OBS, a game console, your phone's camera or your desktop. It's
[MediaMTX](https://github.com/bluenviron/mediamtx) (MIT). It's off until you turn it on.

**How it stays private.**

- The bridge is the media server's only door. For each stream it hands out a key, and for
  each viewer a short-lived token. The media server asks the bridge about every connection,
  and the bridge checks who it is and who may watch. Stopping a stream, or taking someone's
  access away, drops them at once.
- The media server's control API, and its questions to the bridge, listen only on the pod's
  loopback. No Service and no tailnet forward ever carries them.
- Every address BRODEC is given is on your private network: your lab's tailnet, or your LAN.
  Nothing here is reachable from the internet.
- People away from your private network watch through a TURN relay, if you set one: the
  media server and the viewer both connect out to it, and nothing connects into your lab.
- **A live stream is not end-to-end encrypted like your messages.** It's encrypted on the way
  (WebRTC's DTLS-SRTP, SRT's passphrase, your tailnet's WireGuard), and it reaches only the
  viewers the bridge let in, but the media server in your lab sees the picture and sound.

**Turn it on.**

```bash
helm upgrade brodec-lab oci://ghcr.io/bromigos-org/charts/brodec-lab -n brodec-lab --reuse-values \
  --set mediaServer.enabled=true \
  --set mediaServer.tailnet.enabled=true \
  --set mediaServer.tailnet.loginServer=https://net.example.org \
  --set mediaServer.tailnet.authKeySecret.name=brodec-media-tailnet \
  --set mediaServer.host=100.64.0.7
```

1. Make a one-time pre-auth key on your lab network for the media server's node, and put it
   in a Secret: `kubectl -n brodec-lab create secret generic brodec-media-tailnet
   --from-literal=auth_key=...`. Tag it so that only your own devices may reach it.
2. Install with `mediaServer.tailnet` as above. Once the node has joined, set
   `mediaServer.host` to its tailnet address and upgrade again.
3. In BRODEC, **GO LIVE** appears for this lab.

| Value | What it does |
|---|---|
| `mediaServer.enabled` | The media server and the bridge's streaming. Off by default |
| `mediaServer.host` | The address your devices reach it at on your private network (required) |
| `mediaServer.tailnet.*` | This pod joins your tailnet in userspace and forwards only the media ports: RTMP 1935, WebRTC 8889, ICE 8189, HLS 8888, and recordings' playback 9996 |
| `mediaServer.consoles.enabled`, `mediaServer.consoleHost`, `mediaServer.consoles.allowFrom` | A LoadBalancer Service on your LAN for game consoles (RTMP) and SRT, which can't join a tailnet. Off by default. Set `allowFrom` to your LAN's range |
| `mediaServer.recording.existingClaim`, `mediaServer.recording.keepDays` | Recordings on a volume you provide, such as your NAS share, deleted after `keepDays` (0 keeps them) |
| `mediaServer.relay.turnUrl`, `mediaServer.relay.secret` | A TURN relay, so people away from your private network can watch. Its shared secret stays in its Secret |
| `mediaServer.maxStreams`, `mediaServer.maxViewers` | Streams at once (1), and viewers per stream (10) |
| `mediaServer.guests` | People you share the lab with as Can ask may go live too |
| `mediaServer.transcode` | `none` passes streams through as sent. `opus` gives WebRTC viewers sound when a stream's sound is AAC, as OBS's RTMP sends; it's cheap. `abr` makes a quality ladder; give the pod a GPU. Both use MediaMTX's ffmpeg image |

The media server passes streams through as they arrive. For the lowest delay, use OBS's
WHIP output (OBS 30 or later): its sound plays over WebRTC as it is. RTMP's AAC sound plays
over HLS, a few seconds behind, unless `transcode` is `opus`.

## His name

VECTOR is his name until you give him another: **Settings › Your lab › NAME** in BRODEC.
A name has up to 24 characters: letters, digits, spaces, hyphens and basic punctuation. It
can't look like BRODEC, BROMIGOS or anyone's callsign, and you can rename him five times a
day. Going back to VECTOR is always allowed.

The bridge checks the name too, then uses it as his name on BRODEC. The people you share
your lab with see it. Only his name changes: he looks, sounds and works the same.

## Switching VECTOR back on

You can switch VECTOR off from anywhere: **Settings › Your lab › SWITCH VECTOR OFF** in
BRODEC, or `/off` in your chat with him. Only your lab can switch him back on. Give the
chart's switch Secret a new value:

```bash
kubectl -n brodec-lab patch secret brodec-lab-switch \
  -p "{\"stringData\":{\"on\":\"$(date -u +%FT%TZ)\"}}"
```

He comes back within a minute. An old value never turns him on, so a value that was there
before he went off doesn't count. Upgrades keep the Secret's value.

Pausing reports from your phone is different: it only stops the reports, and you resume
them from your phone.

## Its security settings

- One replica, replaced, never two at once. It is one device on your account.
- It runs as user 10001, with a read-only root filesystem and no Linux capabilities.
- It has no service account token and no RBAC.
- Its data, `persistence`, holds its identity. Uninstalling keeps the volume. If you lose
  it, pair the lab again.
- The media server, when on, runs with the same settings: user 10001, a read-only root
  filesystem, no capabilities. Its control API and the bridge's auth hook stay on the pod's
  loopback.
- The NetworkPolicy, on by default, lets it reach DNS, HTTPS and the ports of the sources and
  brain you set. Nothing may connect in, except the media server's ports from your LAN when
  `mediaServer.consoles` is on. BRODEC's servers run on public cloud addresses, so HTTPS can't be narrowed to
  an address range. Add rules with `networkPolicy.extraEgress`. The policy needs a network
  plugin that enforces NetworkPolicy.

## Remove it

Disconnect the lab in BRODEC first: **Settings › Your lab › DISCONNECT LAB**. Then:

```bash
helm uninstall brodec-lab -n brodec-lab
kubectl -n brodec-lab delete pvc brodec-lab-data secret brodec-lab-switch
```

The second line deletes the bridge's identity and its switch. Leave it out to reinstall later
without pairing again.

## For contributors

The chart's tests render it with several sets of values and check the results:

```bash
python3 homelab/charts/brodec-lab/tests/test_chart.py
```

How the chart, the image and the package are published:
[packaging/README.md, "BRODEC's lab bridge"](../../../packaging/README.md#brodecs-lab-bridge).
