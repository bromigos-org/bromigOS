# Agents in your lab

The provisioner generates public-safe settings for Hermes Agent, OpenClaw and NVIDIA
NemoClaw. Agents call an existing OpenAI-compatible model endpoint. They do not need a
GPU themselves. This page records the upstream research and the installer boundaries.
The [manual](../manual/src/lab.md#setting-up-agents) explains how to use them.

## Upstream projects

Checked on 2026-10-10 against each project's own repository and documentation.

| Project | What it is | Licence | Deployment and settings |
|---|---|---|---|
| Hermes Agent | Nous Research's personal agent with persistent memory and messaging | MIT | Official `nousresearch/hermes-agent` container; `config.yaml`, environment credentials and profile state |
| OpenClaw | A personal AI agent with a gateway and optional messaging channels | MIT | Official `ghcr.io/openclaw/openclaw` container or Node.js CLI; JSON5 `openclaw.json` |
| NVIDIA NemoClaw | A reference stack that runs supported agents inside NVIDIA OpenShell | Apache-2.0 | Native installer and CLI create a managed gateway and sandbox; network policy and inference configuration |

Hermes can run directly from its Python CLI or in its official container. The container
supervises `hermes gateway run`. A native installation can use
`hermes gateway install` for a Linux user service. Its API uses port 8642. Models can use a custom
OpenAI-compatible endpoint. Telegram and Discord need separate bot tokens and sender
allowlists. Memory and profile state live in its persistent home folder. Sources:
[repository and licence](https://github.com/NousResearch/hermes-agent),
[container installation](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/docker.md),
[model configuration](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/configuring-models.md),
[profiles](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/profiles.md)
and [configuration](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/configuration.md).

OpenClaw's Node.js CLI runs `openclaw gateway`. Its npm install and
`openclaw onboard --install-daemon` can install a native background service. Its official containers publish version
tags. The gateway uses port 18789. Custom providers accept an OpenAI-compatible base URL,
API key and served model ID. Tool allowlists, explicit denies and messaging sender rules
are part of its configuration. Sources:
[repository and licence](https://github.com/openclaw/openclaw),
[containers](https://github.com/openclaw/openclaw/blob/main/docs/install/docker.md),
[configuration](https://github.com/openclaw/openclaw/blob/main/docs/gateway/configuration-reference.md),
[tool policy](https://github.com/openclaw/openclaw/blob/main/docs/gateway/config-tools/tool-policy.md)
and [gateway](https://github.com/openclaw/openclaw/blob/main/docs/gateway/config-gateway.md).

NemoClaw is NVIDIA's project. It supports OpenClaw, Hermes and LangChain Deep Agents.
It is not a separate model. The CLI selects the inference provider and creates an
OpenShell sandbox. Network policy uses YAML; the managed agent keeps its own
OpenClaw JSON5 or Hermes YAML settings. It can attach to a trusted private OpenAI-compatible endpoint.
Remote inference needs no local GPU. Local NVIDIA inference has separate GPU and driver
requirements. Its documented minimum is four CPUs, 8 GB RAM and 20 GB free disk. It
needs a supported container runtime and Node.js 22.19 or newer. Sources:
[repository and licence](https://github.com/NVIDIA/NemoClaw),
[prerequisites](https://github.com/NVIDIA/NemoClaw/blob/main/docs/get-started/prerequisites.mdx),
[installation](https://github.com/NVIDIA/NemoClaw/blob/main/docs/get-started/quickstart.mdx),
[compatible endpoints](https://github.com/NVIDIA/NemoClaw/blob/main/docs/inference/set-up-openai-compatible-endpoint.mdx)
and [commands](https://github.com/NVIDIA/NemoClaw/blob/main/docs/reference/commands.mdx).

### Remote MCP servers

*MCP* is the Model Context Protocol, a standard way for an agent to call an outside
service's tools. A remote MCP server is one web address the agent connects to. Checked on
2026-11-17 against the documentation of the versions the provisioner pins: Hermes Agent
v0.21.6 and OpenClaw 2026.9.9.

Hermes reads remote servers from `mcp_servers` in `config.yaml`. An entry has a `url` and
optional `headers`. A header's value may name an environment variable as `${VAR}`. Hermes
doesn't connect when that variable is unset. Every server is offered on every surface,
unless a surface's `platform_toolsets` list names servers. Then only the named ones are.
A server may ask the agent's model for text (`sampling`) and ask the person a question
(`elicitation`) unless its entry turns them off. Sources:
[MCP configuration reference](https://github.com/NousResearch/hermes-agent/blob/v0.21.6/website/docs/reference/mcp-config-reference.md),
[MCP guide](https://github.com/NousResearch/hermes-agent/blob/v0.21.6/website/docs/user-guide/features/mcp.md),
[toolsets reference](https://github.com/NousResearch/hermes-agent/blob/v0.21.6/website/docs/reference/toolsets-reference.md)
and [ACP](https://github.com/NousResearch/hermes-agent/blob/v0.21.6/website/docs/user-guide/features/acp.md),
which states the rule for `platform_toolsets`.

A Hermes server entry also has a `trust` key, `full` or `untrusted`. The default is `full`,
and any other word counts as `untrusted`. On an `untrusted` server, a call to a tool
needs the person's approval before it runs, unless the server marks that tool
`readOnlyHint: true`. The mark is the server's own word. A prompt that gets no answer
within `approvals.timeout`, 300 seconds by default, is not run. A client of the API
server's `/v1/runs` gets an `approval.request` event and answers it with
`POST /v1/runs/{run_id}/approval`. Sources: the MCP configuration reference above,
[API server](https://github.com/NousResearch/hermes-agent/blob/v0.21.6/website/docs/user-guide/features/api-server.md)
and [security](https://github.com/NousResearch/hermes-agent/blob/v0.21.6/website/docs/user-guide/security.md).

OpenClaw reads them from `mcp.servers` in `openclaw.json`. A remote entry has a `url`,
`transport: "streamable-http"` and optional `headers`. Any string in the file may name an
environment variable as `${VAR}`. A server's tools are named `<server>__<tool>`, and the
tool allowlist takes `*` wildcards. Its tool policy has no approval step for an MCP
server's tools: a tool is allowed or it isn't. Sources:
[MCP transports](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/cli/mcp/transports.md),
[MCP, skills and plugins](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/gateway/config-extensions.md),
[environment and secrets](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/gateway/config-secrets-env.md)
and [tool policy](https://github.com/openclaw/openclaw/blob/v2026.9.9/docs/gateway/config-tools/tool-policy.md).

The provisioner builds its own generic Helm chart for Hermes and OpenClaw. It does not
claim that either project ships this chart. NemoClaw uses its native host deployment.
No operator chart, personal profile, private memory plugin or bot configuration ships
with bromigOS.

## Plan and credentials

All three catalog entries provide the `agent` role and depend on `llm-gateway`.
An existing endpoint entry provides `llm-gateway` and `llm-server`. Agent selections use
that entry. This avoids installing a second inference server in a lab that already has
LiteLLM, Ollama or vLLM. The plan can offer an endpoint already configured in the console.
The user confirms a URL reachable from the target, including `/v1`.

The user can choose an LLM from the model catalog, then enter the model ID served by their
endpoint. An existing external model is also supported. This slice downloads no model
weights and installs no new Ollama, LiteLLM or vLLM server.

Planning prompts for profile, messaging channels, numeric sender IDs, tools and
[connectors](#connectors). Hidden prompts collect API keys, bot tokens and connector keys. Credentials enter sops through stdin. Only age
ciphertext enters the generated repository. An age recipient is needed even when Vault
will be installed, because credentials must survive the interval between plan and apply.
Apply also stores them in Vault when selected. Runtime credentials use root-owned files
on the target or Kubernetes Secrets. They never appear in generated values or command
arguments. Repeated planning reuses the encrypted credentials.

Hermes uses persistent memory when `memory` tools are selected. Its chosen profile has
an isolated persistent home and one gateway. Shell, file, browser, code execution,
delegation, skills, web and cron tools are disabled on the generated messaging and API
surfaces. OpenClaw also denies shell, file, UI, node and automation tools. Its exact
allowlist excludes other plugin tools, apart from the tools of the connectors you chose.
OpenClaw keeps its memory files; semantic memory search is off until an embedding
endpoint is configured. Its
messaging channels use explicit sender allowlists and disable group messages.

Hermes and OpenClaw host API ports bind to loopback. Cluster services use ClusterIP. The generated
cluster workloads mount no host directories and receive no service account token.
Disks have Helm keep annotations. Reapplying never deletes their state.

## NemoClaw boundaries

NemoClaw has a native Linux host plan. It installs a reviewed source revision and creates
one restricted OpenClaw sandbox. This native path has plan tests; it has not yet
passed the live VM test used for Hermes and OpenClaw. It refuses an unrelated existing installation. Later
applies keep that sandbox and reapply its tool restrictions. The provisioner never
requests sandbox recreation. Changing its inference configuration needs a separate
upstream review.

Messaging stays disabled for NemoClaw in this slice. Its managed images enable a broader
tool set by default. The provisioner refuses messaging selections rather than allowing
those tools to reach a bot. Cluster-only NemoClaw installation is also refused. Its
upstream managed Docker/OpenShell gateway is not an ordinary application Helm chart.

## Connectors

A *connector* is an entry in the [connector catalogue](lab-connectors.md) that is a remote
MCP server. Hermes and OpenClaw can be given the connectors that need nothing or an API
key. The agent gets those servers' tools and no other new tool.

### Choose connectors

Name them when you plan, by their ids from `bromigos lab connectors`:

```bash
bromigos lab provision --services hermes --ssh <user>@<host> --repo <folder> \
  --age-recipient <age-public-key> --llm-url <model-url> --connectors context7 tavily
```

`<user>@<host>` is your Linux box, `<folder>` is your lab repository, `<age-public-key>`
is your age public key and `<model-url>` is your model endpoint.

Without `--connectors`, planning asks for them after the tools question. Press Enter for
none. Every agent in the plan gets the same connectors.

A saved plan keeps its choice when you run `add` or `remove`. A plan made before
connectors existed keeps none. To change the choice, pass `--connectors` again. With no id
after it, `--connectors` removes them all.

| Option | What it does |
|---|---|
| `--connectors <id>…` | Give the agents these connectors. At most eight. |
| `--allow-acting <id>…` | Also allow a chosen connector that can spend money or contact people. |
| `--allow-unanswered <id>…` | Also allow a chosen connector whose address didn't answer the catalogue's check. |
| `--trust-connector <id>…` | Let Hermes run a chosen connector's write calls without asking first. |

The plan's summary lists each connector with its address, at plan and again before apply.

### What planning refuses

The provisioner checks each id against the catalogue, when you plan and again when you
apply. It stops, and says why, for any of these:

| The id | What the message says |
|---|---|
| Isn't in the catalogue | No connector has that id. It names close ones. |
| Is a key platform | Key platforms come in a later change. |
| Needs a sign-in in a browser | Sign-in connectors come in a later change. |
| Is `listed only` | The entry's own reason. |
| Has no address, or runs on your own machine | An agent in your lab can't reach it. |
| Didn't answer the catalogue's check | The day and the answer. `--allow-unanswered <id>` allows it. |
| Can spend money or contact people | What it can do. `--allow-acting <id>` allows it. |

More than eight connectors are refused too. So is any connector for NemoClaw.

The entries that can spend money or contact people are the ones with an `acts` key. See
[Entries that can spend money or contact people](lab-connectors.md#entries-that-can-spend-money-or-contact-people).
A summary line says "Allowed to act" for each one you allowed.

### Write calls ask first

Hermes gets every connector as an `untrusted` server. A *write call* is a call to a tool
that its server doesn't mark as read-only. Hermes asks before each one, and a read call
runs without asking. A server that marks none of its tools asks for every call.

| Where the agent is used | What happens to a write call |
|---|---|
| Telegram or Discord | The chat that made the request gets an approval prompt. Only your allowed user IDs can use that chat. With no answer in 300 seconds, the call isn't run. |
| The API server's `/v1/runs` | The run waits. Your client answers the `approval.request` event. |
| The API server's chat completions | Nobody can be asked, so plan for the call not to run. |

The last row comes from reading Hermes's source, in a checkout a little older than the
pinned version. Upstream's documentation describes no way to ask on that endpoint. No
test here has run it.

To let one connector's write calls run without asking, name it with
`--trust-connector <id>`. Its server entry gets `trust: full`. A connector that can spend
money or contact people can only be trusted when `--allow-acting` names it too, because
planning refuses it otherwise. The plan's summary says which connectors are trusted.

OpenClaw has no setting like this. Its documentation gives no approval step for a
connector's tools, so OpenClaw runs a chosen connector's write calls without asking, and
`--trust-connector` changes nothing for it. Give OpenClaw only connectors you would trust.

### Keys

A connector that needs a key gets a hidden prompt, once for the whole plan. The key then
travels the way the agent's other credentials do:

1. It enters sops through stdin. Only age ciphertext enters the repository.
2. Apply stores it in Vault when Vault is selected.
3. Apply writes it to the agent's root-owned env file on the box, or to the agent's
   Kubernetes Secret, through stdin.
4. The agent's container reads it from an environment variable named after the connector,
   such as `CONNECTOR_TAVILY_KEY`.

The generated settings hold `${CONNECTOR_TAVILY_KEY}`, never the key. The key isn't in
`plan.json`, in a command's arguments or in the summary. Planning again reuses the
encrypted key. When you stop choosing a connector, the next plan drops its key from the
encrypted credentials.

### Generated settings

Each connector becomes a server named `connector_<id>`, with hyphens as underscores. The
prefix keeps a server's name apart from an agent's own tool groups.

For Hermes, `config.yaml` gets an `mcp_servers` entry for each server: its `url`, and for
a key an `Authorization: Bearer` header, or the header the catalogue names. Sampling and
elicitation are off, so a server can't use the agent's model or question the person. Its
`trust` is `untrusted`, or `full` for a connector you trusted. Each
surface's `platform_toolsets` list names the servers. Hermes would offer them without
that, but a list that names servers offers only those.

For OpenClaw, `openclaw.json` gets the same servers under `mcp.servers`, with
`transport: "streamable-http"`. Its tool allowlist gains `connector_<id>__*` for each
server, which matches that server's tools only.

Nothing else changes. Hermes still has shell, file, browser, code execution, delegation,
skills, web and cron tools disabled. OpenClaw's deny list is the same.

### Network

The generated workloads have no egress rule or network policy, with or without
connectors. The agent's container can reach the chosen servers, and anything else its
network allows.

### What isn't built

> **Planned.** Sign-in connectors and key platforms can't be given to an agent yet.
> NemoClaw is given no connectors. Choosing one tool of a server, instead of all of them,
> isn't built either.

## Read-only console

The Agents card shows the selected agent's health, model and gateway metadata. Its
connectors column lists the plan's connectors that the running agent has a server for, by
id and name. A server's address and key never reach the card. Hermes
reports connected platform states, active work and heartbeat time. OpenClaw reports
configured channels and the last session metadata update. A configured channel is not
labelled connected unless a live status says so. NemoClaw reports managed sandbox
readiness. No adapter reads messages, transcripts, logs, env files or Secret values.
The doctor checks live agent health along with the other selected services.

## Tests

`test_agentprovision.py` checks the catalog and resolver, complete host and cluster plan
goldens, tool restrictions, sender rules and credential handling. Its metadata test
ensures extra payload fields cannot enter a console row. For connectors it checks host and
cluster goldens with two connectors, each refusal, the `trust` each server gets, that
every other setting stays as it was, and that a key appears in no generated file, argument
or output.

`test/vm/lab-agents-e2e.py` boots a fresh Debian guest. It installs real Hermes and
OpenClaw containers against a local OpenAI-compatible stub, checks health and a real
agent response, then repeats apply and checks the doctor. Messaging is disabled. It
checks that captured output and repository files contain no test credential values.
Cleanup stops the guest and removes its disk and test keys. It gives the agents no
connector, so no test starts a real agent with one yet.
