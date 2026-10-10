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

Planning prompts for profile, messaging channels, numeric sender IDs and tools. Hidden
prompts collect API keys and bot tokens. Credentials enter sops through stdin. Only age
ciphertext enters the generated repository. An age recipient is needed even when Vault
will be installed, because credentials must survive the interval between plan and apply.
Apply also stores them in Vault when selected. Runtime credentials use root-owned files
on the target or Kubernetes Secrets. They never appear in generated values or command
arguments. Repeated planning reuses the encrypted credentials.

Hermes uses persistent memory when `memory` tools are selected. Its chosen profile has
an isolated persistent home and one gateway. Shell, file, browser, code execution,
delegation, skills, web and cron tools are disabled on the generated messaging and API
surfaces. OpenClaw also denies shell, file, UI, node and automation tools. Its exact allowlist excludes other plugin tools.
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

## Read-only console

The Agents card shows the selected agent's health, model and gateway metadata. Hermes
reports connected platform states, active work and heartbeat time. OpenClaw reports
configured channels and the last session metadata update. A configured channel is not
labelled connected unless a live status says so. NemoClaw reports managed sandbox
readiness. No adapter reads messages, transcripts, logs, env files or Secret values.
The doctor checks live agent health along with the other selected services.

## Tests

`test_agentprovision.py` checks the catalog and resolver, complete host and cluster plan
goldens, tool restrictions, sender rules and credential handling. Its metadata test
ensures extra payload fields cannot enter a console row.

`test/vm/lab-agents-e2e.py` boots a fresh Debian guest. It installs real Hermes and
OpenClaw containers against a local OpenAI-compatible stub, checks health and a real
agent response, then repeats apply and checks the doctor. Messaging is disabled. It
checks that captured output and repository files contain no test credential values.
Cleanup stops the guest and removes its disk and test keys.
