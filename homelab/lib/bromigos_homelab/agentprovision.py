"""Reviewed upstream agent configurations and deployment plans. No credential values here."""
import getpass
import hashlib
import json
import re
import secrets
from urllib.parse import urlsplit

AGENTS = ('hermes', 'openclaw', 'nemoclaw')
IMAGES = {'hermes': 'nousresearch/hermes-agent:v0.21.6@sha256:55e192fba0cd4fde61142abbff5adeacff40efdb482ccd0ff877924bd274f909',
          'openclaw': 'ghcr.io/openclaw/openclaw:2026.9.9@sha256:7f10d5cc975a90b65192eaa099454fe33ce8ce2390806c61c65cd868e9ef730d',
}
PORTS = {'hermes': 8642, 'openclaw': 18789}
NEMO_REF = '2bbb4d1e3a25a49e3a9508c5e49de772afb8cded'
SAFE_HERMES = ('memory', 'session_search', 'todo')
DENIED_HERMES = ('terminal', 'file', 'browser', 'code_execution', 'delegation', 'skills', 'web', 'cronjob')


def validate(options, picked, target):
    from .provision import ProvisionError
    if not any(s in picked for s in AGENTS):
        return
    url = urlsplit(options.get('endpoint', ''))
    if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ProvisionError('Agents need a credential-free HTTP(S) OpenAI-compatible --llm-url ending in /v1')
    if not url.path.rstrip('/').endswith('/v1'):
        raise ProvisionError('The LLM URL must include /v1')
    if not options.get('model') or not re.fullmatch(r'[a-zA-Z0-9_.:/-]+', options['model']):
        raise ProvisionError('Choose a served model ID')
    if options.get('catalog_model') and options['catalog_model'] != 'external':
        from . import catalog
        model = catalog.load().models.get(options['catalog_model'])
        if not model or 'llm' not in model.caps:
            raise ProvisionError('The catalog model must support LLM calls')
    if options.get('tools', 'memory') not in ('none', 'memory'):
        raise ProvisionError('Agent tool choice must be none or memory; shell and file tools stay disabled')
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,31}', options.get('profile', 'assistant')):
        raise ProvisionError('Use a short lower-case profile name')
    channels = options.get('gateways', [])
    if set(channels) - {'telegram', 'discord'}:
        raise ProvisionError('Choose Telegram or Discord')
    for channel in channels:
        ids = options.get(channel + '_users', [])
        if not ids or any(not re.fullmatch(r'[0-9]+', str(i)) for i in ids):
            raise ProvisionError(channel + ' needs explicit numeric allowed user IDs')
    if 'nemoclaw' in picked:
        if target['kind'] != 'ssh':
            raise ProvisionError('NemoClaw needs its own Linux Docker/OpenShell host; cluster-only installation is not supported upstream')
        if channels:
            raise ProvisionError('NemoClaw messaging remains disabled until its managed image tool restrictions can be enforced')


def configure(picked, options, saved=None):
    """Hidden prompts; caller encrypts the returned values before any plan write."""
    from . import catalog
    if not any(s in picked for s in AGENTS):
        return options, {}
    options = dict(options)
    if not options.get('endpoint'):
        from . import config
        candidates = [s for s in config.load().get('sources', []) if s.get('type') in ('litellm', 'openai', 'ollama') and s.get('endpoint')]
        candidates.sort(key=lambda s: s.get('type') != 'litellm')
        default = candidates[0]['endpoint'].rstrip('/') if candidates else ''
        if default and not default.endswith('/v1'):
            default += '/v1'
        parsed = urlsplit(default)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            default = ''
        options['endpoint'] = input('OpenAI-compatible LLM URL, including /v1' + (' [' + default + ']' if default else '') + ': ').strip() or default
    if not options.get('model'):
        models = [m for m in catalog.load().models.values() if 'llm' in m.caps]
        print('Model catalog choices: ' + ', '.join(m.id for m in models))
        options['catalog_model'] = input('Catalog model ID (or external for an existing served model): ').strip()
        if options['catalog_model'] != 'external' and options['catalog_model'] not in {m.id for m in models}:
            from .provision import ProvisionError
            raise ProvisionError('Choose a model from the catalog or external')
        options['model'] = input('Model ID reported by your endpoint: ').strip()
    if 'gateways' not in options:
        choice = input('Messaging gateways: none, telegram, discord, or telegram discord [none]: ').strip()
        options['gateways'] = [] if not choice or choice == 'none' else choice.split()
    if not options.get('profile'):
        options['profile'] = input('Profile name [assistant]: ').strip() or 'assistant'
    if not options.get('tools'):
        options['tools'] = input('Allowed tools: none or memory [memory]; shell and file tools are disabled: ').strip() or 'memory'
    for channel in options['gateways']:
        if not options.get(channel + '_users'):
            options[channel + '_users'] = [v.strip() for v in input(channel + ' allowed numeric user IDs, separated by commas: ').strip().split(',')]
    credentials = dict(saved or {})
    for agent in picked:
        if agent not in AGENTS:
            continue
        name = agent + '-env'
        env = dict(credentials.get(name, {}))
        if not env.get('LLM_API_KEY'):
            env['LLM_API_KEY'] = getpass.getpass(agent + ' LLM API key (blank only for an unauthenticated endpoint): ') or 'no-key-required'
        env.setdefault('AGENT_API_KEY', secrets.token_urlsafe(32))
        for channel in options['gateways']:
            variable = channel.upper() + '_BOT_TOKEN'
            if not env.get(variable):
                env[variable] = getpass.getpass(agent + ' ' + channel + ' bot token: ')
                if not env[variable]:
                    from .provision import ProvisionError
                    raise ProvisionError('The selected messaging gateway needs a token')
        credentials[name] = env
    return options, credentials


def configuration(agent, options):
    model, endpoint = options['model'], options['endpoint']
    gateways = options.get('gateways', [])
    if agent == 'hermes':
        tools = list(SAFE_HERMES) if options.get('tools', 'memory') == 'memory' else []
        return {'model': {'provider': 'custom', 'default': model, 'base_url': endpoint, 'api_mode': 'chat_completions'},
                'auxiliary': {k: {'provider': 'main', 'model': model} for k in ('compression', 'vision', 'web_extract')},
                'memory': {'memory_enabled': 'memory' in tools, 'user_profile_enabled': 'memory' in tools},
                'agent': {'disabled_toolsets': list(DENIED_HERMES)},
                'platform_toolsets': {k: tools for k in ('telegram', 'discord', 'api_server', 'cron')},
                'security': {'redact_secrets': True, 'allow_lazy_installs': False},
                'gateway': {'multiplex_profiles': False, 'unauthorized_dm_behavior': 'ignore'},
                'platforms': {'api_server': {'enabled': True, 'extra': {'host': '0.0.0.0', 'port': 8642}},
                              **{k: {'enabled': k in gateways} for k in ('telegram', 'discord')}}}
    tools = ['session_status', 'memory_get'] if options.get('tools', 'memory') == 'memory' else ['session_status']
    channels = {}
    for channel in gateways:
        cfg = {'enabled': True, 'dmPolicy': 'allowlist', 'allowFrom': options[channel + '_users'], 'groupPolicy': 'disabled'}
        cfg['botToken' if channel == 'telegram' else 'token'] = '${' + channel.upper() + '_BOT_TOKEN}'
        channels[channel] = cfg
    return {'gateway': {'mode': 'local', 'bind': 'lan', 'port': 18789, 'auth': {'mode': 'token', 'token': '${AGENT_API_KEY}'},
                        'controlUi': {'enabled': False}, 'http': {'endpoints': {'chatCompletions': {'enabled': True}}}},
            'models': {'mode': 'merge', 'providers': {'lab': {'baseUrl': endpoint, 'apiKey': '${LLM_API_KEY}', 'api': 'openai-completions',
                                                            'models': [{'id': model, 'name': model}]}}},
            'agents': {'defaults': {'model': {'primary': 'lab/' + model}, 'workspace': '/home/node/.openclaw/workspace', 'memorySearch': {'enabled': False}},
                       'entries': {options.get('profile', 'assistant'): {'name': options.get('profile', 'assistant')}}},
            'tools': {'allow': tools, 'deny': ['group:runtime', 'group:fs', 'group:ui', 'group:nodes', 'group:automation', 'sessions_spawn', 'subagents']},
            'channels': channels, 'commands': {'bash': False, 'config': False, 'debug': False, 'restart': False, 'nativeSkills': False}, 'logging': {'redactSensitive': 'tools'}, 'discovery': {'mdns': {'mode': 'off'}}}


def environment(agent, options, credentials):
    env = dict(credentials)
    if agent == 'hermes':
        env.update(OPENAI_API_KEY=env['LLM_API_KEY'], CUSTOM_API_KEY=env['LLM_API_KEY'], CUSTOM_BASE_URL=options['endpoint'],
                   API_SERVER_ENABLED='true', API_SERVER_HOST='0.0.0.0', API_SERVER_KEY=env['AGENT_API_KEY'])
        for channel in options.get('gateways', []):
            env[channel.upper() + '_ALLOWED_USERS'] = ','.join(options[channel + '_users'])
    return env


def plan(files, state, roles):
    from . import provision as P
    picked, target = state['selected'], state['target']
    chosen = [a for a in AGENTS if a in picked]
    if not chosen:
        return
    opts = state['agents']
    validate(opts, picked, target)
    box = target['kind'] == 'ssh'
    containers = {}
    resources = []
    for agent in chosen:
        if agent == 'nemoclaw':
            continue
        config = configuration(agent, opts)
        name = 'config.yaml' if agent == 'hermes' else 'openclaw.json'
        files[f'agents/{agent}/{name}'] = P.dump(config)
        files[f'helm/{agent}/values.yaml'] = P.dump({agent: {'image': IMAGES[agent]}})
        command = ['hermes', '-p', 'default', 'gateway', 'run'] if agent == 'hermes' else ['node', 'openclaw.mjs', 'gateway', '--allow-unconfigured']
        home = '/opt/data/' + opts.get('profile', 'assistant') if agent == 'hermes' else '/home/node/.openclaw'
        cfg = {'image': IMAGES[agent], 'restart': 'unless-stopped', 'command': command,
               'ports': [f'127.0.0.1:{PORTS[agent]}:{PORTS[agent]}'], 'env_file': [f'./{agent}.env'],
               'volumes': [f'{agent}-data:{home}', f'./{agent}/{name}:{home}/{name}:ro'],
               'cap_drop': ['ALL'], 'security_opt': ['no-new-privileges:true'], 'extra_hosts': ['lab-model-host:host-gateway']}
        if agent == 'hermes':
            cfg['environment'] = {'HERMES_SKIP_CONFIG_MIGRATION': '1', 'HERMES_HOME': home}
            # s6 needs a writable runtime directory and user switch support.
            cfg.pop('cap_drop')
        if agent == 'openclaw':
            cfg['volumes'][-1] = './openclaw/openclaw.json:/etc/lab/openclaw.json:ro'
            cfg['entrypoint'] = ['/bin/sh', '-ec', 'cp /etc/lab/openclaw.json /home/node/.openclaw/openclaw.json; exec tini -s -- node /app/docker-entrypoint.mjs "$$@"', 'lab-init']
        containers[agent] = cfg
        labels = {'app': agent}
        resources += [{'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim', 'metadata': {'name': agent + '-data'},
                       'spec': {'accessModes': ['ReadWriteOnce'], 'resources': {'requests': {'storage': '5Gi'}}}},
                      {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': agent + '-config'}, 'data': {name: P.dump(config)}},
                      {'apiVersion': 'apps/v1', 'kind': 'Deployment', 'metadata': {'name': agent},
                       'spec': {'replicas': 1, 'strategy': {'type': 'Recreate'}, 'selector': {'matchLabels': labels},
                                'template': {'metadata': {'labels': labels}, 'spec': {'automountServiceAccountToken': False,
                                    'containers': [{'name': agent, 'image': '{{ .Values.' + agent + '.image }}', 'command': command,
                                        'envFrom': [{'secretRef': {'name': agent + '-env'}}],
                                        'env': [{'name': 'HERMES_SKIP_CONFIG_MIGRATION', 'value': '1'}, {'name': 'HERMES_HOME', 'value': home}] if agent == 'hermes' else [],
                                        'ports': [{'containerPort': PORTS[agent]}],
                                        'readinessProbe': {'httpGet': {'path': '/health' if agent == 'hermes' else '/healthz', 'port': PORTS[agent]}, 'initialDelaySeconds': 15},
                                        'resources': {'requests': {'memory': '512Mi', 'cpu': '250m'}},
                                        'volumeMounts': [{'name': 'data', 'mountPath': home}, {'name': 'config', 'mountPath': home + '/' + name, 'subPath': name, 'readOnly': True}]}],
                                    'initContainers': [{'name': 'state-owner', 'image': 'busybox:1.37.0', 'command': ['/bin/sh', '-ec', 'chown 1000:1000 /state'], 'volumeMounts': [{'name': 'data', 'mountPath': '/state'}]}],
                                    'volumes': [{'name': 'data', 'persistentVolumeClaim': {'claimName': agent + '-data'}}, {'name': 'config', 'configMap': {'name': agent + '-config'}}]}}}},
                      {'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': agent}, 'spec': {'type': 'ClusterIP', 'selector': labels, 'ports': [{'port': PORTS[agent]}]}}]
    if not box:
        for resource in resources:
            if resource['kind'] != 'Deployment' or resource['metadata']['name'] != 'openclaw':
                continue
            pod = resource['spec']['template']['spec']
            pod['containers'][0]['volumeMounts'] = [m for m in pod['containers'][0]['volumeMounts'] if m['name'] != 'config']
            pod['initContainers'][0]['command'][-1] = 'cp /defaults/openclaw.json /state/openclaw.json; chown 1000:1000 /state /state/openclaw.json'
            pod['initContainers'][0]['volumeMounts'].append({'name': 'config', 'mountPath': '/defaults', 'readOnly': True})
    if box and containers:
        files['agents/compose.yaml'] = P.dump({'services': containers, 'volumes': {a + '-data': {} for a in containers}})
        roles.append('agents')
        packages = {'debian': ['docker.io', 'docker-compose'], 'ubuntu': ['docker.io', 'docker-compose'], 'fedora': ['moby-engine', 'docker-compose'], 'arch': ['docker', 'docker-compose']}[state['inventory']['distribution']]
        files['ansible/roles/agents/tasks/main.json'] = P.dump([
            P.task('Install agent container engine', 'ansible.builtin.package', {'name': packages, 'state': 'present', 'update_cache': True}),
            P.task('Start agent container engine', 'ansible.builtin.systemd', {'name': 'docker', 'state': 'started', 'enabled': True}),
            P.task('Copy reviewed agent settings', 'ansible.builtin.copy', {'src': '{{ playbook_dir }}/../../agents/', 'dest': '/opt/bromigos-agents/', 'mode': '0644', 'directory_mode': '0755'}),
            P.task('Converge agents without removing volumes', 'ansible.builtin.shell', {'cmd': 'if docker compose version >/dev/null 2>&1; then docker compose -p bromigos-agents up -d; else docker-compose -p bromigos-agents up -d; fi', 'chdir': '/opt/bromigos-agents'}, changed_when=False)])
    if not box and resources:
        for doc in resources:
            doc['metadata']['annotations'] = {'helm.sh/resource-policy': 'keep'}
        files['helm/agents/values.yaml'] = P.dump({a: {'image': IMAGES[a]} for a in containers})
        files['helm/agents/Chart.yaml'] = 'apiVersion: v2\nname: lab-agents\nversion: 0.1.0\n'
        files['helm/agents/templates/agents.yaml'] = '---\n'.join(P.dump(d) for d in resources)
        roles.append('agents')
        args = ['helm', 'upgrade', '--install', 'lab-agents', '{{ playbook_dir }}/../../helm/agents', '--namespace', 'lab-agents', '--create-namespace', '--description', 'bromigos-lab-provision', '--kubeconfig', target['kubeconfig'], '--kube-context', target['context'], '--wait', '--timeout', '10m'] + [p for a in containers for p in ['--values', '{{ playbook_dir }}/../../helm/' + a + '/values.yaml']]
        files['ansible/roles/agents/tasks/main.json'] = P.dump([
            P.task('Read agents release ownership', 'ansible.builtin.command', {'argv': ['helm', 'status', 'lab-agents', '-n', 'lab-agents', '-o', 'json', '--kubeconfig', target['kubeconfig'], '--kube-context', target['context']]}, register='agent_release', failed_when=False, changed_when=False),
            P.task('Check agents ownership', 'ansible.builtin.assert', {'that': ["agent_release.rc != 0 or (agent_release.stdout | from_json).info.description == 'bromigos-lab-provision'"]}),
            P.task('Converge agents', 'ansible.builtin.command', {'argv': args}, changed_when=False)])
        if 'argocd' in picked:
            files['gitops/argocd-apps/agents.yaml'] = P.dump({'apiVersion': 'argoproj.io/v1alpha1', 'kind': 'Application', 'metadata': {'name': 'lab-agents', 'namespace': 'argocd'}, 'spec': {'project': 'default', 'source': {'repoURL': state['git_url'], 'targetRevision': 'HEAD', 'path': 'helm/agents', 'helm': {'releaseName': 'lab-agents', 'valueFiles': ['../' + a + '/values.yaml' for a in containers]}}, 'destination': {'server': 'https://kubernetes.default.svc', 'namespace': 'lab-agents'}, 'syncPolicy': {'automated': {'prune': False, 'selfHeal': True}}}})
    if 'nemoclaw' in chosen:
        files['agents/README.md'] = '# Agent settings\n\nNemoClaw uses its own managed OpenShell host. Messaging is disabled.\nChanging its model endpoint requires a new reviewed upstream plan; this installer never recreates a sandbox.\n'
        # Upstream owns the nested gateway and sandbox. Never recreate an existing sandbox.
        roles.append('nemoclaw')
        fingerprint = hashlib.sha256(P.dump(opts).encode()).hexdigest()
        files['agents/nemoclaw.json'] = P.dump({'source': 'https://github.com/NVIDIA/NemoClaw', 'revision': NEMO_REF, 'agent': 'openclaw', 'model': opts['model'], 'endpoint': opts['endpoint'], 'policy': 'restricted', 'messaging': 'disabled'})
        files['ansible/roles/nemoclaw/tasks/main.json'] = P.dump([
            P.task('Install NemoClaw prerequisites', 'ansible.builtin.package', {'name': ['curl', 'git', 'binutils', 'zstd', 'docker.io'] if state['inventory']['distribution'] in ('debian', 'ubuntu') else ['curl', 'git', 'binutils', 'zstd', 'moby-engine' if state['inventory']['distribution'] == 'fedora' else 'docker'], 'state': 'present'}),
            P.task('Start NemoClaw engine', 'ansible.builtin.systemd', {'name': 'docker', 'state': 'started', 'enabled': True}),
            P.task('Check for an unrelated NemoClaw installation', 'ansible.builtin.shell', {'cmd': 'test -f /opt/bromigos-nemoclaw/installed || { test ! -e /root/.nemoclaw && test ! -e /root/.openshell && test ! -e /root/.local/bin/nemoclaw && ! command -v nemoclaw >/dev/null 2>&1; }'}, changed_when=False),
            P.task('Refuse a changed existing sandbox plan', 'ansible.builtin.shell', {'cmd': 'test ! -f /opt/bromigos-nemoclaw/installed || grep -qx ' + fingerprint + ' /opt/bromigos-nemoclaw/installed'}, changed_when=False),
            P.task('Fetch reviewed NemoClaw source', 'ansible.builtin.git', {'repo': 'https://github.com/NVIDIA/NemoClaw', 'dest': '/opt/bromigos-nemoclaw/source', 'version': NEMO_REF, 'update': False}),
            P.task('Install and onboard a new restricted sandbox', 'ansible.builtin.shell', {'cmd': 'set -eu; set -a; . /opt/bromigos-agents/nemoclaw.env; set +a; bash /opt/bromigos-nemoclaw/source/install.sh; echo ' + fingerprint + ' > /opt/bromigos-nemoclaw/installed', 'creates': '/opt/bromigos-nemoclaw/installed'}, environment={'NEMOCLAW_INSTALL_REF': NEMO_REF, 'NEMOCLAW_NON_INTERACTIVE': '1', 'NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE': '1', 'NEMOCLAW_SANDBOX_NAME': 'lab-assistant', 'NEMOCLAW_PROVIDER': 'custom', 'NEMOCLAW_ENDPOINT_URL': opts['endpoint'], 'NEMOCLAW_MODEL': opts['model'], 'NEMOCLAW_POLICY_TIER': 'restricted', 'NEMOCLAW_WEB_SEARCH_PROVIDER': 'none', 'NEMOCLAW_TRUSTED_PRIVATE_HOSTS': urlsplit(opts['endpoint']).hostname}),
            P.task('Disable sandbox shell and file tools', 'ansible.builtin.command', {'argv': ['/root/.local/bin/nemoclaw', 'lab-assistant', 'exec', '--', 'openclaw', 'config', 'set', 'tools', json.dumps(configuration('openclaw', opts)['tools'])]}, changed_when=False),
            P.task('Restart the configured sandbox gateway', 'ansible.builtin.command', {'argv': ['/root/.local/bin/nemoclaw', 'lab-assistant', 'gateway', 'restart']}, changed_when=False),
            P.task('Verify managed sandbox', 'ansible.builtin.command', {'argv': ['/root/.local/bin/nemoclaw', 'lab-assistant', 'status']}, changed_when=False)])


def runtime_secrets(state, values):
    """Runtime credentials travel through stdin; only encrypted staging lives on desktop."""
    from . import provision as P
    target = state['target']
    opts = state.get('agents', {})
    chosen = [a for a in AGENTS if a in state['selected']]
    if not chosen:
        return
    if target['kind'] == 'ssh':
        P.run(P.ssh_args(target) + ["sudo -n sh -c 'test ! -e /opt/bromigos-agents || test -f /opt/bromigos-agents/.bromigos-managed'"])
        P.run(P.ssh_args(target) + ["sudo -n install -d -m 0700 /opt/bromigos-agents; sudo -n touch /opt/bromigos-agents/.bromigos-managed"])
    if target['kind'] == 'cluster':
        raw = P.kubectl(target, ['get', 'namespace', 'lab-agents', '--ignore-not-found', '-o', 'json'])
        if raw and json.loads(raw).get('metadata', {}).get('annotations', {}).get('bromigos.org/provisioner') != 'lab-agents':
            raise P.ProvisionError('The lab-agents namespace belongs to another installer')
        P.kubectl(target, ['apply', '-f', '-'], P.dump({'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': 'lab-agents', 'annotations': {'bromigos.org/provisioner': 'lab-agents'}}}))
    for agent in chosen:
        credentials = values.get(agent + '-env')
        if not isinstance(credentials, dict) or not credentials.get('LLM_API_KEY') or not credentials.get('AGENT_API_KEY'):
            raise P.ProvisionError('Agent credentials are missing; run plan with your age identity available')
        env = environment(agent, opts, credentials)
        if agent == 'nemoclaw':
            env = {'COMPATIBLE_API_KEY': credentials['LLM_API_KEY']}
        if target['kind'] == 'ssh':
            # POSIX-quoted env files are suitable for both dotenv and the NemoClaw shell.
            import shlex
            text = ''.join(k + '=' + shlex.quote(v) + '\n' for k, v in env.items())
            command = "sudo -n install -d -m 0700 /opt/bromigos-agents; sudo -n sh -c 'umask 077; cat > /opt/bromigos-agents/" + agent + ".env'"
            P.run(P.ssh_args(target) + [command], text)
        else:
            P.kubectl(target, ['apply', '-f', '-'], P.dump({'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': agent + '-env', 'namespace': 'lab-agents'}, 'type': 'Opaque', 'stringData': env}))


# Whitelist metadata at the source. Never read messages, logs, env files or Secret values.
HERMES_METADATA = '''import json, os
from pathlib import Path
import urllib.request
home = Path(os.environ.get("HERMES_HOME", "/opt/data"))
config = json.loads((home / "config.yaml").read_text())
status = json.loads((home / "gateway_state.json").read_text())
urllib.request.urlopen("http://127.0.0.1:8642/health", timeout=5).read()
print(json.dumps({"status": "running", "model": config.get("model", {}).get("default", "unknown"), "gateways": ", ".join(k + ": " + str(v.get("state", "unknown")) for k,v in status.get("platforms", {}).items() if k in ("telegram", "discord", "api_server")), "activity": str(status.get("active_agents", 0)) + " active; heartbeat " + str(status.get("updated_at", "unknown"))}))
'''
OPENCLAW_METADATA = '''const fs = require('fs');
const c = JSON.parse(fs.readFileSync('/home/node/.openclaw/openclaw.json', 'utf8'));
fetch('http://127.0.0.1:18789/healthz').then(r => {if(!r.ok) process.exit(1); const p='/home/node/.openclaw/agents'; let last=0; function visit(d) {if(!fs.existsSync(d)) return; for(const e of fs.readdirSync(d,{withFileTypes:true})){const q=d+'/'+e.name;if(e.isDirectory())visit(q);else if(e.name==='sessions.json')last=Math.max(last,fs.statSync(q).mtimeMs);}} visit(p); console.log(JSON.stringify({status:'running',model:c.agents.defaults.model.primary,gateways:Object.keys(c.channels||{}).map(k=>k+': configured (connection unknown)').join(', ') || 'none',activity:last ? 'session metadata updated '+new Date(last).toISOString() : 'no recorded sessions'}));}).catch(()=>process.exit(1));
'''


def metadata(state, agent):
    from . import provision as P
    import shlex
    target = state['target']
    if agent == 'nemoclaw':
        # exec selects the owning gateway. The inner HTTP check makes no model call.
        argv = ['/root/.local/bin/nemoclaw', 'lab-assistant', 'exec', '--', 'node', '-e', OPENCLAW_METADATA.replace('/home/node', '/sandbox')]
        raw = json.loads(P.run(P.ssh_args(target) + ['sudo -n ' + shlex.join(argv)]))
        return {'name': agent, **{k: raw.get(k, 'unknown') for k in ('status', 'model', 'gateways', 'activity')}}
    argv = ['python3', '-c', HERMES_METADATA] if agent == 'hermes' else ['node', '-e', OPENCLAW_METADATA]
    if target['kind'] == 'ssh':
        command = 'sudo -n docker exec $(sudo -n docker ps -q --filter label=com.docker.compose.project=bromigos-agents --filter label=com.docker.compose.service=' + agent + ') ' + shlex.join(argv)
        result = P.run(P.ssh_args(target) + [command])
    else:
        result = P.kubectl(target, ['-n', 'lab-agents', 'exec', 'deployment/' + agent, '--'] + argv)
    raw = json.loads(result)
    return {'name': agent, **{k: raw.get(k, 'unknown') for k in ('status', 'model', 'gateways', 'activity')}}


def verify(state):
    from . import provision as P
    for agent in AGENTS:
        if agent in state['selected']:
            if metadata(state, agent)['status'] != 'running':
                raise P.ProvisionError(agent + ' health check failed')
