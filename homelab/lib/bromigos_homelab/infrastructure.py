"""Reviewed multi-node plans, VM lifecycle and capacity proposals. No automatic growth."""
import argparse
import copy
import getpass
import ipaddress
import json
from pathlib import Path
import re
import secrets
import shlex
import time
import os

from . import provision as P, vmproviders as V, observability as O


def label(value):
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,40}', str(value)):
        raise P.ProvisionError('Use a short lower-case name')
    return value


def validate(spec):
    V.load_extensions()
    nodes = spec.get('nodes', [])
    if not nodes or sum(n.get('role') == 'server' for n in nodes) not in (1, 3):
        raise P.ProvisionError('A cluster needs one or three control-plane servers')
    if spec.get('distribution', 'debian') not in ('debian', 'ubuntu', 'fedora', 'arch'):
        raise P.ProvisionError('Choose a supported Linux distribution for the cloud image')
    names, addresses, ids = set(), set(), set()
    for name, options in spec.get('providers', {}).items():
        label(name)
        if options.get('type') not in V.PROVIDERS: raise P.ProvisionError('Unknown VM provider')
        if options.get('target'): P.validate_target(options['target'])
        if not options.get('target') and options.get('sudo'): raise P.ProvisionError('Never run desktop sudo')
        if options.get('type') == 'proxmox':
            V.Proxmox(options)
            label(options.get('pool', ''))
    for n in nodes:
        label(n['name'])
        if n['name'] in names: raise P.ProvisionError('Node names must be unique')
        names.add(n['name'])
        if n.get('role') not in ('server', 'worker', 'gpu'): raise P.ProvisionError('Node role must be server, worker or gpu')
        for value in n.get('labels', []):
            if not re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?=[A-Za-z0-9_.-]*', value): raise P.ProvisionError('Use Kubernetes key=value node labels')
        for value in n.get('taints', []):
            if not re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?=[A-Za-z0-9_.-]*:(?:NoSchedule|PreferNoSchedule|NoExecute)', value): raise P.ProvisionError('Use key=value:effect node taints')
        if 'vm' not in n:
            P.validate_target(n['target'])
            if n['target']['kind'] != 'ssh': raise P.ProvisionError('Existing nodes need SSH targets')
            continue
        if n.get('on') not in spec.get('providers', {}): raise P.ProvisionError('Choose a configured VM provider')
        vm = n['vm']
        if vm.get('name') != n['name']: raise P.ProvisionError('VM and node names must match')
        kind = spec['providers'][n['on']]['type']
        if (n['on'], str(vm.get('id', vm['name']))) in ids: raise P.ProvisionError('VM IDs must be unique')
        ids.add((n['on'], str(vm.get('id', vm['name']))))
        for field, minimum in [('cpu', 1), ('ram_mib', 2048), ('disk_gib', 20)]:
            if type(vm.get(field)) != int or vm[field] < minimum: raise P.ProvisionError('VM sizes must meet k3s minimums')
        address = ipaddress.ip_interface(vm['address'])
        gateway = ipaddress.ip_address(vm['gateway'])
        if address.version != 4 or not address.ip.is_private or address.ip in addresses or gateway not in address.network:
            raise P.ProvisionError('Use unique private IPv4 addresses and a gateway in the same subnet')
        addresses.add(address.ip)
        for dns in vm.get('dns', []): ipaddress.ip_address(dns)
        if not re.fullmatch(r'[a-z_][a-z0-9_-]*', vm.get('user', '')): raise P.ProvisionError('Choose a cloud-init user')
        if not vm.get('ssh_public_key', '').startswith(('ssh-ed25519 ', 'ssh-rsa ')) or '\n' in vm['ssh_public_key']:
            raise P.ProvisionError('Supply one SSH public key; private keys never enter the plan')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', vm.get('storage', '')): raise P.ProvisionError('Choose a storage pool')
        if vm.get('vlan') is not None and (type(vm['vlan']) != int or not 1 <= vm['vlan'] <= 4094): raise P.ProvisionError('VLAN must be 1 through 4094')
        if kind == 'proxmox':
            if not str(vm.get('id', '')).isdigit() or not str(vm.get('template', '')).isdigit(): raise P.ProvisionError('Proxmox needs numeric VM and template IDs')
            if not re.fullmatch(r'[A-Za-z0-9_.-]+', vm.get('bridge', '')): raise P.ProvisionError('Choose a network bridge')
            if vm.get('gpu_mapping') and not re.fullmatch(r'[A-Za-z0-9_.-]+', vm['gpu_mapping']): raise P.ProvisionError('Use an administrator-defined GPU mapping')
        elif kind == 'kvm':
            if not vm.get('image', '').startswith('/'): raise P.ProvisionError('KVM needs an existing qcow2 cloud image on its host')
            if not re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}', vm.get('mac', '')): raise P.ProvisionError('Supply a unique VM MAC address')
            if not re.fullmatch(r'[A-Za-z0-9_.-]+', vm.get('network') or vm.get('bridge', '')): raise P.ProvisionError('Choose a libvirt network or bridge')
            if vm.get('gpu_pci') and (len(vm['gpu_pci']) != 4 or any(not re.fullmatch(r'0x[0-9a-f]+', x) for x in vm['gpu_pci'])): raise P.ProvisionError('GPU PCI address needs four hexadecimal components')
        V.PROVIDERS[kind].validate_spec(vm)
    if not spec.get('age_recipient', '').startswith('age1'): raise P.ProvisionError('Supply an age recipient for cluster and provider credentials')
    path = str(spec.get('volume_path', '/var/lib/rancher/k3s/storage'))
    if not re.fullmatch(r'/[A-Za-z0-9_./-]+', path) or path in ('/', '/etc', '/boot', '/dev', '/proc', '/sys') or '..' in path.split('/'):
        raise P.ProvisionError('Volume path must be absolute')
    nas = spec.get('nas')
    if nas:
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', nas.get('server', '')) or not re.fullmatch(r'/[A-Za-z0-9_./-]+', nas.get('export', '')):
            raise P.ProvisionError('NAS storage needs an existing NFS server and export')
        if not re.fullmatch(r'/mnt/[a-zA-Z0-9_.-]+', nas.get('mount', '')):
            raise P.ProvisionError('Choose a dedicated /mnt/<name> folder for the NAS share')
        if spec.get('storage_class') == 'lab-nfs': raise P.ProvisionError('Keep Prometheus TSDB and Grafana SQLite on local or block storage, not NFS')
    # Never accept raw secrets in a desired-state specification.
    def no_secrets(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if re.search(r'password|token|private_key|api_key|secret', key, re.I): raise P.ProvisionError('Credentials belong in hidden prompts, not the specification')
                no_secrets(item)
        elif isinstance(value, list):
            for item in value: no_secrets(item)
    no_secrets(spec)


def target(spec, node):
    if 'vm' not in node: return node['target']
    vm = node['vm']
    out = {'kind': 'ssh', 'ssh': vm['user'] + '@' + str(ipaddress.ip_interface(vm['address']).ip), 'port': 22,
           'identity': spec.get('identity', ''), 'known_hosts': spec.get('known_hosts', '')}
    jump = spec['providers'][node['on']].get('target')
    if jump: out['jump'] = jump
    return out


def hostvars(t):
    values = {'ansible_host': t['ssh'].split('@')[1], 'ansible_user': t['ssh'].split('@')[0], 'ansible_port': t.get('port', 22), 'ansible_ssh_common_args': shlex.join(P.ssh_args(t)[1:-1])}
    if t.get('identity'): values['ansible_ssh_private_key_file'] = t['identity']
    return values


def plan(spec, observations=None):
    spec = copy.deepcopy(spec)
    for node in spec.get('nodes', []):
        if 'vm' in node: node['vm'].setdefault('distribution', spec.get('distribution', 'debian'))
    validate(spec)
    owner = spec.setdefault('owner', V.fingerprint(spec))
    if not re.fullmatch(r'[a-z0-9]{8,24}', owner): raise P.ProvisionError('Invalid plan ownership ID')
    first = next(n for n in spec['nodes'] if n['role'] == 'server')
    primary = target(spec, first)
    # Planning newly allocated guests uses their declared sizes, never invented inventory.
    observed = (observations or {}).get('nodes', {})
    if any('vm' not in n and n['name'] not in observed for n in spec['nodes']): raise P.ProvisionError('Existing nodes need read-only inventory before planning')
    facts = {'cpu': sum(n['vm']['cpu'] if 'vm' in n else observed[n['name']]['cpu'] for n in spec['nodes']),
             'ram_gib': sum(n['vm']['ram_mib']/1024 if 'vm' in n else observed[n['name']]['ram_gib'] for n in spec['nodes']),
             'disk_gib': sum(n['vm']['disk_gib'] if 'vm' in n else observed[n['name']]['disk_gib'] for n in spec['nodes']),
             'distribution': spec.get('distribution', 'debian'), 'architecture': 'x86_64', 'gpu': 'none', 'vram_gib': 0}
    files, resolved = P.plan_files(primary, ['kubernetes', 'helm'] + spec.get('services', []), facts,
        age_recipient=spec['age_recipient'], repo_url=spec.get('git_url', ''), backup_path=spec.get('backup_path', ''),
        storage_class=spec.get('storage_class', 'local-path'), agents=spec.get('agents'))
    state = json.loads(files['plan.json'])
    state['infrastructure'] = spec
    state['storage_inventory'] = observations or {}
    state['capacity_basis'] = 'declared VM sizes; apply checks each guest before installation'
    state['review_notes'] = ['VM disks and local-path volumes are not redundant unless host RAID proves otherwise.',
        'Multiple control planes on one hypervisor do not survive loss of that hypervisor.',
        'No RAID arrays, storage pools or NAS shares will be created or formatted.']
    files['plan.json'] = P.dump(state)
    files['infrastructure.json'] = P.dump(spec)
    servers = [n for n in spec['nodes'] if n['role'] == 'server']
    plays = []
    inventory = {'all': {'hosts': {n['name']: hostvars(target(spec, n)) for n in spec['nodes']}}}
    for index, n in enumerate(sorted(spec['nodes'], key=lambda n: n['role'] != 'server')):
        if spec.get('existing_cluster') and n['role'] == 'server': continue
        config = {'node-name': n['name'], 'token': '{{ lab_join_token }}', 'node-label': ['bromigos.org/managed=true'] + n.get('labels', [])}
        if n['role'] == 'server':
            config.update({'disable': ['traefik', 'servicelb'], 'secrets-encryption': True})
            if len(servers) == 3 and n == first: config['cluster-init'] = True
        if n == first: config['node-label'].append('bromigos.org/primary=true')
        if n != first: config['server'] = 'https://' + primary['ssh'].split('@')[1] + ':6443'
        if n['role'] == 'gpu':
            config['node-label'].append('bromigos.org/gpu=true')
            config['node-taint'] = ['nvidia.com/gpu=true:NoSchedule']
        if n.get('taints'): config.setdefault('node-taint', []).extend(n['taints'])
        role = 'k3s-' + n['name']
        tasks = [P.task('Check existing k3s configuration', 'ansible.builtin.stat', {'path': '/etc/rancher/k3s/config.yaml'}, register='existing_k3s'),
            P.task('Check plan ownership', 'ansible.builtin.stat', {'path': '/etc/rancher/k3s/bromigos-' + owner}, register='owned_k3s'),
            P.task('Refuse an unrelated cluster', 'ansible.builtin.assert', {'that': ['not existing_k3s.stat.exists or owned_k3s.stat.exists']}),
            P.task('Check pre-existing k3s binary', 'ansible.builtin.stat', {'path': '/usr/local/bin/k3s'}, register='existing_binary'),
            P.task('Refuse an unowned k3s installation', 'ansible.builtin.assert', {'that': ['not existing_binary.stat.exists or owned_k3s.stat.exists']}),
            P.task('Install cluster prerequisites', 'ansible.builtin.package', {'name': ['curl', 'iptables', 'python' if facts['distribution'] == 'arch' else 'python3'], 'state': 'present', 'update_cache': True}),
            P.task('Create k3s folder', 'ansible.builtin.file', {'path': '/etc/rancher/k3s', 'state': 'directory', 'mode': '0700'}),
            P.task('Write protected cluster configuration', 'ansible.builtin.copy', {'content': P.dump(config), 'dest': '/etc/rancher/k3s/config.yaml', 'mode': '0600'}, no_log=True, register='cluster_config'),
            P.task('Mark cluster ownership', 'ansible.builtin.copy', {'content': owner + '\n', 'dest': '/etc/rancher/k3s/bromigos-' + owner, 'mode': '0600'}),
            P.task('Download k3s installer', 'ansible.builtin.get_url', {'url': 'https://get.k3s.io', 'dest': '/opt/bromigos-k3s-install.sh', 'mode': '0700'}),
            P.task('Install pinned k3s node', 'ansible.builtin.command', {'argv': ['/opt/bromigos-k3s-install.sh', 'server' if n['role'] == 'server' else 'agent'],
                'creates': '/etc/systemd/system/k3s.service' if n['role'] == 'server' else '/etc/systemd/system/k3s-agent.service'}, environment={'INSTALL_K3S_VERSION': P.K3S, 'INSTALL_K3S_SKIP_START': 'true'}, no_log=True),
            P.task('Keep cluster node running', 'ansible.builtin.systemd', {'name': 'k3s' if n['role'] == 'server' else 'k3s-agent', 'state': '{{ "restarted" if cluster_config.changed else "started" }}', 'enabled': True})]
        if n['role'] == 'gpu':
            tasks[:0] = [P.task('Check GPU driver', 'ansible.builtin.command', {'argv': ['nvidia-smi', '--query-gpu=name', '--format=csv,noheader']}, changed_when=False),
                P.task('Check NVIDIA container runtime', 'ansible.builtin.command', {'argv': ['which', 'nvidia-container-runtime']}, changed_when=False)]
        if spec.get('nas'): tasks[:0] = nas_tasks(spec['nas'], facts['distribution'])
        if n == first:
            tasks += [P.task('Write bounded k3s bootstrap check', 'ansible.builtin.copy', {'content': Path(__file__).with_name('k3sbootstrap.py').read_text(), 'dest': '/opt/bromigos-k3s-bootstrap.py', 'mode': '0700'}),
                      P.task('Wait for owned k3s bootstrap definitions', 'ansible.builtin.command', {'argv': ['python3', '/opt/bromigos-k3s-bootstrap.py', '/etc/rancher/k3s/bromigos-' + owner]}, register='bootstrap_result', changed_when="'bootstrap-reconciled' in bootstrap_result.stdout")]
        if n == first: tasks.append(P.task('Wait for control plane', 'ansible.builtin.command', {'argv': ['k3s', 'kubectl', 'wait', '--for=condition=Ready', 'node/' + n['name'], '--timeout=300s']}, changed_when=False))
        files['ansible/roles/' + role + '/tasks/main.json'] = P.dump(tasks)
        plays.append({'name': 'Converge node ' + n['name'], 'hosts': n['name'], 'become': True, 'gather_facts': False, 'roles': [role]})
    files['ansible/inventory/hosts.json'] = P.dump(inventory)
    files['ansible/playbooks/cluster.json'] = P.dump(plays)
    existing = json.loads(files['ansible/playbooks/provision.json'])
    existing[0]['hosts'] = first['name']
    existing[0]['roles'] = [r for r in existing[0]['roles'] if r != 'k3s']
    if spec.get('nas'):
        files['helm/nas/values.yaml'] = P.dump({'nfs': {'server': spec['nas']['server'], 'path': spec['nas']['export'], 'reclaimPolicy': 'Retain'},
            'storageClass': {'name': 'lab-nfs', 'defaultClass': False, 'reclaimPolicy': 'Retain', 'onDelete': 'retain'}})
        existing[0]['roles'].insert(existing[0]['roles'].index('monitoring'), 'nas')
        files['ansible/roles/nas/tasks/main.json'] = P.dump(chart_tasks('lab-nfs', 'https://kubernetes-sigs.github.io/nfs-subdir-external-provisioner/', 'nfs-subdir-external-provisioner', '4.0.18', '/opt/bromigos-lab/helm/nas.yaml'))
    if any(n['role'] == 'gpu' for n in spec['nodes']):
        existing[0]['roles'].append('gpu-monitoring')
        files['helm/nvidia-device-plugin/values.yaml'] = P.dump({'runtimeClassName': 'nvidia', 'nodeSelector': {'bromigos.org/gpu': 'true'}, 'tolerations': [{'key': 'nvidia.com/gpu', 'operator': 'Exists', 'effect': 'NoSchedule'}]})
        files['helm/dcgm-exporter/values.yaml'] = P.dump({'runtimeClassName': 'nvidia', 'nodeSelector': {'bromigos.org/gpu': 'true'}, 'tolerations': [{'key': 'nvidia.com/gpu', 'operator': 'Exists', 'effect': 'NoSchedule'}], 'serviceMonitor': {'enabled': True}})
        files['ansible/roles/gpu-monitoring/tasks/main.json'] = P.dump(chart_tasks('lab-device-plugin', 'https://nvidia.github.io/k8s-device-plugin', 'nvidia-device-plugin', '0.20.1', '/opt/bromigos-lab/helm/nvidia-device-plugin.yaml') + chart_tasks('lab-dcgm', 'https://nvidia.github.io/dcgm-exporter/helm-charts', 'dcgm-exporter', '4.8.4', '/opt/bromigos-lab/helm/dcgm-exporter.yaml'))
    files['ansible/playbooks/provision.json'] = P.dump(existing)
    files['ansible/playbooks/bootstrap.json'] = P.dump([{**existing[0], 'roles': ['helm']}])
    extra_path = 'helm/monitor-extra/templates/resources.yaml'
    documents = [json.loads(d) for d in files[extra_path].split('---\n')]
    blackbox = documents[0]['spec']['template']['spec']
    blackbox.pop('nodeSelector', None)
    blackbox['nodeName'] = first['name']
    files[extra_path] = '---\n'.join(P.dump(d) for d in documents)
    files['README.md'] += '\nThis cluster plan allocates only named VMs after explicit approval.\nCluster and provider credentials are encrypted in secrets.enc.json.\n'
    return files, resolved


def nas_tasks(nas, distro):
    package = 'nfs-common' if distro in ('debian', 'ubuntu') else 'nfs-utils'
    source = nas['server'] + ':' + nas['export']; mount = nas['mount']
    return [P.task('Install NFS client', 'ansible.builtin.package', {'name': package, 'state': 'present'}),
        P.task('Read existing NAS mount', 'ansible.builtin.command', {'argv': ['findmnt', '-n', '-M', mount, '-o', 'SOURCE']}, register='nas_mount', failed_when=False, changed_when=False),
        P.task('Refuse a conflicting NAS mount', 'ansible.builtin.assert', {'that': ['nas_mount.rc != 0 or nas_mount.stdout == ' + json.dumps(source)]}),
        P.task('Create NAS mount folder', 'ansible.builtin.file', {'path': mount, 'state': 'directory', 'mode': '0755'}),
        P.task('Mount the existing NFS share', 'ansible.builtin.command', {'argv': ['mount', '-t', 'nfs', '-o', 'hard,nosuid,nodev', source, mount]}, when='nas_mount.rc != 0'),
        P.task('Keep the NAS mount after reboot', 'ansible.builtin.lineinfile', {'path': '/etc/fstab', 'line': source + ' ' + mount + ' nfs _netdev,hard,nosuid,nodev,x-systemd.automount 0 0', 'create': False})]


def chart_tasks(release, repo, chart, version, dest):
    env = {'KUBECONFIG': '/etc/rancher/k3s/k3s.yaml'}
    return [P.task('Copy ' + chart + ' values', 'ansible.builtin.copy', {'src': '{{ playbook_dir }}/../../helm/' + chart + '/values.yaml' if chart != 'nfs-subdir-external-provisioner' else '{{ playbook_dir }}/../../helm/nas/values.yaml', 'dest': dest, 'mode': '0600'}),
        P.task('Read ' + release + ' ownership', 'ansible.builtin.command', {'argv': ['helm', 'status', release, '-n', 'monitoring', '-o', 'json']}, register='existing_release', environment=env, failed_when=False, changed_when=False),
        P.task('Refuse unrelated ' + release, 'ansible.builtin.assert', {'that': ["existing_release.rc != 0 or (existing_release.stdout | from_json).info.description == 'bromigos-lab-provision'"]}),
        P.task('Converge ' + release, 'ansible.builtin.command', {'argv': ['helm', 'upgrade', '--install', release, chart, '--namespace', 'monitoring', '--repo', repo, '--version', version, '--description', 'bromigos-lab-provision', '--values', dest, '--wait', '--timeout', '10m']}, environment=env, changed_when=False)]


def storage_health(mdstat='', zpool=''):
    rows = []
    for block in re.split(r'\n(?=md\S+\s*:)', mdstat):
        if not re.match(r'md\S+\s*:', block): continue
        level = re.search(r'\b(raid\d+|linear)\b', block)
        state = re.search(r'\[([U_]+)\]', block)
        rows.append({'name': block.split(':')[0].strip(), 'kind': level[1] if level else 'unknown',
            'redundancy': bool(level and level[1] not in ('raid0', 'linear')),
            'health': 'degraded' if state and '_' in state[1] else 'healthy' if state else 'unknown'})
    pool = None
    for line in zpool.splitlines():
        if line.strip().startswith('pool:'):
            pool = {'name': line.split(':', 1)[1].strip(), 'kind': 'zfs', 'redundancy': False, 'health': 'unknown'}; rows.append(pool)
        elif pool and line.strip().startswith('state:'): pool['health'] = 'healthy' if line.split(':')[1].strip() == 'ONLINE' else 'degraded'
        elif pool and re.search(r'\b(raidz[123]?|mirror)-', line): pool['redundancy'] = True
    return rows


def storage_inventory(spec, credentials):
    out = {}
    for name, options in spec.get('providers', {}).items():
        backend = V.provider(options, credentials.get('provider-' + name, ''), spec.get('owner', ''))
        pools = backend.storage()
        existing = backend.list()
        host = options.get('target')
        raid = []
        if host:
            mdstat = P.run(P.ssh_args(host) + ['if test -r /proc/mdstat; then cat /proc/mdstat; fi'])
            zpool = P.run(P.ssh_args(host) + ["if command -v zpool >/dev/null 2>&1; then zpool status 2>/dev/null || true; fi"])
            raid = storage_health(mdstat, zpool)
        elif options['type'] == 'kvm':
            mdstat = Path('/proc/mdstat').read_text() if Path('/proc/mdstat').exists() else ''
            zpool = P.run(['sh', '-c', 'if command -v zpool >/dev/null 2>&1; then zpool status 2>/dev/null || true; fi'])
            raid = storage_health(mdstat, zpool)
        out[name] = {'pools': pools, 'raid': raid, 'note': 'Unknown redundancy is a warning, not a promise of protection'}
        for node in spec['nodes']:
            if node.get('on') != name or 'vm' not in node: continue
            pool = next((p for p in pools if p['storage'] == node['vm']['storage']), None)
            if not pool or not pool.get('active'): raise P.ProvisionError('Selected VM storage pool is absent or inactive')
        total = {}
        for node in spec['nodes']:
            if node.get('on') == name and 'vm' in node:
                vm = node['vm']
                allocated = any(str(r.get('vmid', r.get('name'))) == str(vm.get('id', vm['name'])) for r in existing)
                if not allocated: total[vm['storage']] = total.get(vm['storage'], 0) + vm['disk_gib'] * 2**30
        for pool, requested in total.items():
            available = next(p for p in pools if p['storage'] == pool).get('avail')
            if available is not None and requested > available: raise P.ProvisionError('Requested VM disks exceed storage pool free space')
    out['nodes'] = {n['name']: P.inventory(n['target']) for n in spec['nodes'] if 'vm' not in n}
    return out


def collect_credentials(spec, saved=None):
    values = dict(saved or {})
    for name, options in spec.get('providers', {}).items():
        prompt = V.PROVIDERS[options['type']].credential_prompt
        if prompt and 'provider-' + name not in values:
            values['provider-' + name] = getpass.getpass(prompt)
            if not values['provider-' + name]: raise P.ProvisionError('A provider credential is required')
    if 'cluster-join-token' not in values:
        values['cluster-join-token'] = getpass.getpass('Existing k3s join credential, hidden (will be encrypted): ') if spec.get('existing_cluster') else secrets.token_urlsafe(48)
        if not values['cluster-join-token']: raise P.ProvisionError('An imported cluster needs its existing join credential')
    if not re.fullmatch(r'[A-Za-z0-9_:./+=-]+', values['cluster-join-token']): raise P.ProvisionError('Join credential has an invalid format')
    values.setdefault('grafana-admin-password', secrets.token_urlsafe(32))
    return values


def review(state):
    spec = state['infrastructure']
    print('Cluster plan: ' + str(sum(n['role'] == 'server' for n in spec['nodes'])) + ' control-plane servers')
    for n in spec['nodes']:
        vm = n.get('vm', {})
        observed = state.get('storage_inventory', {}).get('nodes', {}).get(n['name'], {})
        ram = vm.get('ram_mib', round(observed['ram_gib'] * 1024) if 'ram_gib' in observed else '?')
        print(n['name'] + ': ' + n['role'] + ', ' + n.get('on', 'existing SSH machine') + ', ' + str(vm.get('cpu', observed.get('cpu', '?'))) + ' CPUs, ' + str(ram) + ' MiB RAM, ' + str(vm.get('disk_gib', observed.get('disk_gib', '?'))) + ' GiB disk, pool ' + vm.get('storage', 'existing'))
        if vm.get('gpu_mapping') or vm.get('gpu_pci'):
            print('  GPU passthrough: ' + str(vm.get('gpu_mapping') or vm['gpu_pci']))
    print('Kubernetes volumes: ' + spec.get('storage_class', 'local-path') + ' at ' + spec.get('volume_path', '/var/lib/rancher/k3s/storage'))
    for note in state['review_notes']: print('Review: ' + note)
    print(P.dump(state.get('storage_inventory', {})))
    print('Monitoring: Prometheus, Grafana, Loki, Alertmanager; private endpoints, persistent volumes, node/app/GPU dashboards')
    if state.get('observability', {}).get('migration_note'): print('Review: ' + state['observability']['migration_note'])
    catalog = P.services.load()
    for name in state['selected']:
        service = catalog['service'][name]
        ports = [O.PORTS[name]] if name in O.SERVICES else service.get('ports', [])
        print(service['title'] + ': ports ' + str(ports) + ', needs ' + P.dump(service.get('needs', {})).strip())


def wait_guest(spec, node, backend, repo):
    if 'vm' not in node:
        P.inventory(target(spec, node)); return
    name = node['vm'].get('id', node['name'])
    backend.create(node['vm']); backend.start(name)
    key = ''
    for _ in range(150):
        try:
            key = backend.guest_keys(name)
            if re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/=]+(?: [^\n]*)?', key): break
        except P.ProvisionError: pass
        time.sleep(2)
    else: raise P.ProvisionError('Guest agent did not provide a trusted SSH public key')
    host = target(spec, node)['ssh'].split('@')[1]
    known = Path(spec['known_hosts'])
    current = known.read_text() if known.exists() else ''
    rows = [r for r in current.splitlines() if not r.startswith(host + ' ')]
    P.write(known, '\n'.join(rows + [host + ' ' + key]) + '\n')
    for _ in range(100):
        try: P.inventory(target(spec, node)); return
        except P.ProvisionError: time.sleep(2)
    raise P.ProvisionError('Guest SSH did not become reachable')


def ansible(repo, playbook, values, limit=None):
    # Ansible resolves file names before opening them, so /dev/stdin becomes an
    # unusable pipe path. Its env lookup keeps the value out of argv and files.
    env = dict(os.environ, ANSIBLE_CONFIG=str(repo / 'ansible/ansible.cfg'), ANSIBLE_NO_LOG='true', ANSIBLE_NOCOWS='1',
               ANSIBLE_DEBUG='false', ANSIBLE_DISPLAY_ARGS_TO_STDOUT='false', BROMIGOS_LAB_JOIN_TOKEN=values['cluster-join-token'])
    variables = {'lab_join_token': "{{ lookup('ansible.builtin.env', 'BROMIGOS_LAB_JOIN_TOKEN') }}"}
    P.run(['ansible-playbook', '-i', 'inventory/hosts.json', 'playbooks/' + playbook, '--extra-vars', P.dump(variables)] + (['--limit', limit] if limit else []),
          cwd=repo / 'ansible', env=env)


def apply(repo, joining=None):
    repo = Path(repo).resolve()
    state = json.loads((repo / 'plan.json').read_text())
    spec = state['infrastructure']; validate(spec)
    if joining and not any(n['name'] == joining and n['role'] in ('worker', 'gpu') for n in spec['nodes']):
        raise P.ProvisionError('Growth must name a planned worker or GPU node')
    values = P.decrypt(repo)
    # Fresh provider and RAID reads before the resource-cost decision.
    state['storage_inventory'] = storage_inventory(spec, values)
    review(state)
    warnings = P.selection(P.services.load(), state['selected'], state['inventory'])['warnings']
    if any('unknown' not in w for w in warnings): raise P.ProvisionError('Declared cluster capacity does not fit the selected services')
    if input('Create or converge these nodes and monitoring? Type yes: ').strip() != 'yes': return 0
    live = []
    for node in spec['nodes']:
        options = spec.get('providers', {}).get(node.get('on'))
        backend = V.provider(options, values.get('provider-' + node['on'], ''), spec['owner']) if options else None
        if not joining or node['name'] == joining:
            wait_guest(spec, node, backend, repo)
        facts = P.inventory(target(spec, node))
        if facts['distribution'] != spec.get('distribution', 'debian'):
            raise P.ProvisionError('Guest distribution differs from the reviewed image specification')
        if facts['ram_gib'] < 1.5 or facts['disk_gib'] < 10: raise P.ProvisionError('A node has insufficient free resources')
        live.append(facts)
    if json.loads((repo / 'ansible/playbooks/cluster.json').read_text()): ansible(repo, 'cluster.json', values, limit=joining)
    P.kubectl(state['target'], ['wait', '--for=condition=Ready'] + (['node/' + joining] if joining else ['nodes', '--all']) + ['--timeout=300s'])
    local = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'local-path-config', 'namespace': 'kube-system'},
             'data': {'config.json': json.dumps({'nodePathMap': [{'node': 'DEFAULT_PATH_FOR_NON_LISTED_NODES', 'paths': [spec.get('volume_path', '/var/lib/rancher/k3s/storage')]}]})}}
    # Patch only the storage path; preserve the provisioner's setup/teardown scripts.
    P.kubectl(state['target'], ['-n', 'kube-system', 'patch', 'configmap', 'local-path-config', '--type=merge', '-p', P.dump({'data': local['data']})])
    nodes = json.loads(P.kubectl(state['target'], ['get', 'nodes', '-o', 'json']))['items']
    if {n['name'] for n in spec['nodes']} - {n['metadata']['name'] for n in nodes}: raise P.ProvisionError('Some planned nodes are missing')
    facts = dict(live[next(i for i, n in enumerate(spec['nodes']) if n['role'] == 'server')])
    facts.update(cpu=sum(n['cpu'] for n in live), ram_gib=sum(n['ram_gib'] for n in live), disk_gib=sum(n['disk_gib'] for n in live))
    return P.apply(repo, prepared=True, approved=True, live_facts=facts)


def grow(repo, node, on=None, role='worker'):
    repo = Path(repo).resolve()
    state = json.loads((repo / 'plan.json').read_text())
    if not state.get('infrastructure'): raise P.ProvisionError('Create or import a cluster specification first')
    spec = copy.deepcopy(state['infrastructure'])
    node = copy.deepcopy(node)
    node['role'] = role
    if on: node['on'] = on
    if any(n['name'] == node['name'] for n in spec['nodes']): raise P.ProvisionError('Node already exists in the plan')
    spec['nodes'].append(node)
    files, _ = plan(spec, state.get('storage_inventory'))
    P.generate(repo, files)
    print('Node added to the reviewable plan. Apply will ask for your yes before creating it.')
    return apply(repo, joining=node['name'])


def new_node(state, on, role):
    spec = state['infrastructure']
    on = on or next(iter(spec.get('providers', {})), '')
    name = input('New node name: ').strip(); label(name)
    if on not in spec.get('providers', {}):
        user = input('SSH user on ' + on + ': ').strip()
        return {'name': name, 'role': role, 'on': on, 'target': {'kind': 'ssh', 'ssh': user + '@' + on, 'identity': spec.get('identity', '')}}
    candidates = [n for n in spec['nodes'] if n.get('on') == on and 'vm' in n]
    if not candidates: raise P.ProvisionError('Supply --node-spec for the first VM on this provider')
    original = next((n for n in candidates if n['role'] == role), candidates[-1])
    vm = copy.deepcopy(original['vm'])
    if role != 'gpu':
        vm.pop('gpu_mapping', None); vm.pop('gpu_pci', None)
    vm.update(name=name, cpu=int(input('CPUs [2]: ').strip() or '2'), ram_mib=int(input('RAM MiB [4096]: ').strip() or '4096'),
        disk_gib=int(input('Disk GiB [40]: ').strip() or '40'), address=input('Unused IPv4 address and prefix (for example address/24): ').strip())
    vm['storage'] = input('Storage pool [' + vm['storage'] + ']: ').strip() or vm['storage']
    if spec['providers'][on]['type'] == 'proxmox': vm['id'] = int(input('Unused Proxmox VM ID: ').strip())
    else: vm['mac'] = '52:54:00:' + ':'.join(secrets.token_hex(1) for _ in range(3))
    if role == 'gpu' and not vm.get('gpu_mapping') and not vm.get('gpu_pci'):
        raise P.ProvisionError('Supply a GPU node specification with a prepared image and explicit passthrough mapping')
    return {'name': name, 'role': role, 'on': on, 'vm': vm}


def remove(repo, name):
    repo = Path(repo).resolve(); state = json.loads((repo / 'plan.json').read_text()); spec = state['infrastructure']
    node = next((n for n in spec['nodes'] if n['name'] == name), None)
    if not node: raise P.ProvisionError('Node is not owned by this plan')
    if P.run(['git', 'status', '--porcelain'], cwd=repo).strip(): raise P.ProvisionError('Commit the lab repository before node removal')
    if node['role'] == 'server': raise P.ProvisionError('Control-plane removal needs an etcd quorum and backup procedure; refused here')
    if input('Drain and remove node ' + name + '? Type its name: ').strip() != name: return 0
    # No force, no delete-emptydir-data: workload protection failures stop removal.
    P.kubectl(state['target'], ['drain', name, '--ignore-daemonsets', '--timeout=300s'])
    # Disable the agent even when its retained VM is started again later.
    play = [{'hosts': name, 'become': True, 'gather_facts': False, 'tasks': [P.task('Stop removed worker', 'ansible.builtin.systemd', {'name': 'k3s-agent', 'state': 'stopped', 'enabled': False})]}]
    transient = repo / '.runtime/remove-node.json'
    P.write(transient, P.dump(play))
    try:
        P.run(['ansible-playbook', '-i', 'inventory/hosts.json', str(transient)], cwd=repo / 'ansible',
              env=dict(os.environ, ANSIBLE_CONFIG=str(repo / 'ansible/ansible.cfg'), ANSIBLE_NO_LOG='true'))
    finally:
        transient.unlink(missing_ok=True)
    if node.get('vm'):
        backend = V.provider(spec['providers'][node['on']], P.decrypt(repo).get('provider-' + node['on'], ''), spec['owner'])
        backend.stop(node['vm'].get('id', node['name']))
        if input('Delete the VM disk too? Type DELETE ' + name + ': ').strip() == 'DELETE ' + name:
            backend.delete(node['vm'].get('id', node['name']))
    P.kubectl(state['target'], ['delete', 'node', name])
    spec['nodes'] = [n for n in spec['nodes'] if n['name'] != name]
    # Explicit removal already approved, but dirty desired state must not be silently rewritten.
    files, _ = plan(spec, state.get('storage_inventory')); P.generate(repo, files)
    return 0


def sustained(points, threshold, now=None):
    if len(points) < 15: return False
    points = sorted(points)[-16:]
    if points[-1][0] - points[0][0] < 15 * 60 or any(b[0] - a[0] > 90 for a, b in zip(points, points[1:])): return False
    if now is not None and now - points[-1][0] > 90: return False
    return all(v is not None and v > threshold for _, v in points)


def proposals(query_range, pending_reasons=(), now=None):
    queries = [('CPU pressure', '100*(1-avg by(instance)(rate(node_cpu_seconds_total{mode="idle"}[5m])))', 85),
               ('Memory pressure', '100*(1-node_memory_MemAvailable_bytes/node_memory_MemTotal_bytes)', 90),
               ('Pods need more resources', 'sum(kube_pod_status_unschedulable)', 0)]
    reasons = []
    for reason, query, threshold in queries:
        if reason.startswith('Pods') and not any('Insufficient ' in r for r in pending_reasons): continue
        if any(sustained(r['points'], threshold, now) for r in query_range(query)):
            reasons.append(reason)
    if not reasons: return []
    role = 'gpu' if 'Pods need more resources' in reasons and any('Insufficient nvidia.com/gpu' in r for r in pending_reasons) else 'worker'
    return [{'name': 'Add a ' + role + ' node', 'role': role, 'reason': ', '.join(reasons) + ' for at least 15 minutes',
             'state': 'warn', 'approval': 'User yes required; no VM has been created', 'command': 'bromigos lab provision add-node --repo <folder> --node-spec <file> --role ' + role}]


def main(argv):
    parser = argparse.ArgumentParser(prog='bromigos lab provision', description='Review VM, storage and multi-node Kubernetes plans')
    parser.add_argument('verb', choices=('cluster', 'vm', 'storage', 'add-node', 'remove-node', 'capacity'))
    parser.add_argument('action', nargs='?', default='list')
    parser.add_argument('--repo', required=True)
    parser.add_argument('--spec', help='Cluster specification JSON; no credentials')
    parser.add_argument('--node-spec', help='One node specification JSON')
    parser.add_argument('--role', choices=('worker', 'gpu'), default='worker')
    parser.add_argument('--on', help='Configured provider name, or existing SSH host name')
    parser.add_argument('--name', help='Owned VM ID or name')
    parser.add_argument('--snapshot-name')
    args = parser.parse_args(argv)
    try:
        repo = Path(args.repo).resolve()
        if args.verb == 'cluster':
            if not args.spec: raise P.ProvisionError('Supply --spec with the cluster and storage choices')
            spec = json.loads(Path(args.spec).read_text())
            spec.setdefault('known_hosts', str(repo / '.runtime/known_hosts'))
            validate(spec)
            saved = P.decrypt(repo) if (repo / 'secrets.enc.json').exists() else {}
            credentials = collect_credentials(spec, saved)
            if any(a in spec.get('services', []) for a in P.A.AGENTS):
                spec['agents'], agent_values = P.A.configure(spec['services'], spec.get('agents', {}), saved)
                credentials.update(agent_values)
            observations = storage_inventory(spec, credentials)
            files, _ = plan(spec, observations)
            P.generate(repo, files); P.encrypt(repo, spec['age_recipient'], credentials)
            review(json.loads(files['plan.json']))
            print('Review and commit the repository, then run bromigos lab provision apply --repo ' + shlex.quote(str(repo)))
        elif args.verb == 'add-node':
            state = json.loads((repo / 'plan.json').read_text())
            node = json.loads(Path(args.node_spec).read_text()) if args.node_spec else new_node(state, args.on, args.role)
            return grow(repo, node, args.on, args.role)
        elif args.verb == 'remove-node':
            return remove(repo, args.name or args.action)
        else:
            state = json.loads((repo / 'plan.json').read_text()); spec = state['infrastructure']
            if args.verb == 'capacity':
                from .adapters.provisioned import Provisioned
                print(P.dump(Provisioned({'plan': str(repo / 'plan.json')}).capacity())); return 0
            credentials = P.decrypt(repo)
            if args.verb == 'storage':
                if args.action != 'list': raise P.ProvisionError('Pool and RAID creation is not enabled; no disks will be formatted')
                result = storage_inventory(spec, credentials)
                if 'kubernetes' in state['selected']:
                    try:
                        result['kubernetes'] = json.loads(P.kubectl(state['target'], ['get', 'storageclasses', '-o', 'json']))['items']
                    except P.ProvisionError:
                        result['kubernetes_note'] = 'Kubernetes storage classes are unavailable until the cluster can be reached'
                print(P.dump(result)); return 0
            if args.on not in spec['providers']: raise P.ProvisionError('Choose --on from the plan providers')
            backend = V.provider(spec['providers'][args.on], credentials.get('provider-' + args.on, ''), spec['owner'])
            if args.action == 'delete' and any(n.get('on') == args.on and 'vm' in n and str(n['vm'].get('id', n['name'])) == str(args.name) for n in spec['nodes']):
                raise P.ProvisionError('Use remove-node to drain a planned cluster node before deleting its VM')
            if args.action == 'list': result = backend.list()
            elif args.action == 'console': result = backend.console(args.name)
            elif args.action in ('start', 'stop', 'delete', 'snapshot'):
                if input(args.action + ' owned VM ' + str(args.name) + '? Type its ID/name: ').strip() != str(args.name): return 0
                result = backend.snapshot(args.name, label(args.snapshot_name)) if args.action == 'snapshot' else getattr(backend, args.action)(args.name)
            else: raise P.ProvisionError('VM actions: list, start, stop, delete, snapshot, console; create through a reviewed cluster plan')
            print(P.dump(result))
        return 0
    except (P.ProvisionError, OSError, ValueError, KeyError, TypeError, EOFError, KeyboardInterrupt) as error:
        print('Provisioning stopped: ' + (str(error) if isinstance(error, P.ProvisionError) else 'Invalid or missing infrastructure input'), file=__import__('sys').stderr)
        return 1
