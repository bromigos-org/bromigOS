"""VM lifecycle providers. Tokens stay in memory; every mutation checks ownership."""
import hashlib
import json
from pathlib import Path
import re
import shlex
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from . import provision as P

PROVIDERS = {}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Scoped API tokens must never follow a server-selected endpoint.


def register(name, cls):
    """Extensions register a class implementing Provider, never a shell template."""
    if name in PROVIDERS:
        raise ValueError('Provider already registered')
    PROVIDERS[name] = cls


def load_extensions():
    from . import registry
    if not registry._inst.get('plugins'):
        registry.load_plugins()
        registry._inst['plugins'] = True


def provider(options, credential='', owner=''):
    load_extensions()  # Import provider hooks without resolving any source credentials.
    if options.get('type') not in PROVIDERS:
        raise P.ProvisionError('Unknown VM provider; load its extension first')
    return PROVIDERS[options['type']](options, credential, owner)


def fingerprint(spec):
    return hashlib.sha256(P.dump(spec).encode()).hexdigest()[:20]


class Provider:
    credential_prompt = ''
    def __init__(self, options, credential='', owner=''):
        self.options, self.credential, self.owner = options, credential, owner

    @staticmethod
    def validate_spec(spec):
        """Validate provider-specific fields without contacting any host."""

    def create(self, spec): raise NotImplementedError
    def list(self): raise NotImplementedError
    def start(self, name): raise NotImplementedError
    def stop(self, name): raise NotImplementedError
    def delete(self, name): raise NotImplementedError
    def snapshot(self, name, snapshot): raise NotImplementedError
    def console(self, name): raise NotImplementedError
    def storage(self): raise NotImplementedError
    def guest_keys(self, name): raise NotImplementedError


class Proxmox(Provider):
    credential_prompt = 'Proxmox API token (user@realm!token=secret), hidden: '
    def __init__(self, options, credential='', owner=''):
        super().__init__(options, credential, owner)
        url = urllib.parse.urlsplit(options.get('url', ''))
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise P.ProvisionError('Proxmox needs a credential-free HTTPS URL and a trusted certificate')
        self.base = options['url'].rstrip('/') + '/api2/json'
        self.context = ssl.create_default_context(cafile=options.get('ca_file') or None)
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', options.get('node', '')):
            raise P.ProvisionError('Choose a Proxmox node')
        self.node = '/nodes/' + options['node']

    def request(self, method, path, data=None):
        body = urllib.parse.urlencode(data, doseq=True).encode() if data is not None else None
        req = urllib.request.Request(self.base + path, data=body, method=method,
            headers={'Authorization': 'PVEAPIToken=' + self.credential, 'Content-Type': 'application/x-www-form-urlencoded'})
        try:
            opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=self.context), NoRedirect())
            with opener.open(req, timeout=30) as response:
                return json.load(response)['data']
        except (OSError, ValueError, KeyError) as error:
            if isinstance(error, urllib.error.HTTPError): error.close()
            raise P.ProvisionError('Proxmox request failed; check its certificate, reach and scoped token permissions') from None

    def wait(self, upid):
        if not upid:
            return
        for _ in range(180):
            status = self.request('GET', self.node + '/tasks/' + urllib.parse.quote(upid, safe='') + '/status')
            if status['status'] == 'stopped':
                if status.get('exitstatus') != 'OK':
                    raise P.ProvisionError('Proxmox task failed; inspect its status before retrying')
                return
            time.sleep(2)
        raise P.ProvisionError('Proxmox task timed out; inspect it before retrying')

    def path(self, name):
        if not str(name).isdigit():
            raise P.ProvisionError('Proxmox VM ID must be numeric')
        return self.node + '/qemu/' + str(name)

    def owned(self, name):
        config = self.request('GET', self.path(name) + '/config')
        if not self.owner or 'bromigos-' + self.owner not in config.get('tags', '').split(';'):
            raise P.ProvisionError('Refusing to change a VM that belongs to another plan')
        return config

    def list(self):
        return [{k: row.get(k) for k in ('vmid', 'name', 'status', 'cpus', 'maxmem', 'maxdisk', 'tags', 'template')} for row in self.request('GET', self.node + '/qemu')]

    def storage(self):
        return [{**{k: r.get(k) for k in ('storage', 'type', 'active', 'avail', 'total', 'content')},
                 'redundancy': 'unknown', 'health': 'unknown; inspect host RAID separately'} for r in self.request('GET', self.node + '/storage')]

    def create(self, spec):
        name = spec['id']
        marker = 'bromigos-' + self.owner
        sig = 'plan-' + fingerprint(spec)
        if any(str(r['vmid']) == str(name) for r in self.list()):
            config = self.owned(name)
            if sig not in config.get('tags', '').split(';'):
                raise P.ProvisionError('Existing VM differs from this plan; it will not be rebuilt')
            if 'configured' in config.get('tags', '').split(';'):
                return name
        else:
            template = self.request('GET', self.path(spec['template']) + '/config')
            if not template.get('template') or ':cloudinit' not in template.get('ide2', ''):
                raise P.ProvisionError('Choose an existing cloud-init template with ide2 and a guest agent')
            disk = spec.get('root_disk', 'scsi0')
            size = re.search(r'(?:^|,)size=(\d+(?:\.\d+)?)([GMT])(?:,|$)', template.get(disk, ''))
            if not size or spec['disk_gib'] < float(size[1]) * {'M': 1/1024, 'G': 1, 'T': 1024}[size[2]]:
                raise P.ProvisionError('Choose a disk at least as large as the known template root disk')
            self.wait(self.request('POST', self.path(spec['template']) + '/clone', {
                'newid': name, 'name': spec['name'], 'full': 1, 'storage': spec['storage'], 'pool': self.options['pool'], 'description': marker + ';' + sig}))
            # Never guess ownership if the process died between clone and marking.
            self.wait(self.request('PUT', self.path(name) + '/config', {'tags': marker + ';' + sig}))
        net = 'virtio,bridge=' + spec['bridge'] + (',tag=' + str(spec['vlan']) if spec.get('vlan') else '')
        config = {'cores': spec['cpu'], 'memory': spec['ram_mib'], 'net0': net, 'agent': 'enabled=1',
                  'ciuser': spec['user'], 'sshkeys': urllib.parse.quote(spec['ssh_public_key'], safe=''), 'ipconfig0': 'ip=' + spec['address'] + ',gw=' + spec['gateway']}
        if spec.get('dns'): config['nameserver'] = ' '.join(spec['dns'])
        if spec.get('gpu_mapping'):
            config.update(hostpci0='mapping=' + spec['gpu_mapping'] + ',pcie=1', machine='q35')
        self.wait(self.request('PUT', self.path(name) + '/config', config))
        current = self.request('GET', self.path(name) + '/config')
        disk = spec.get('root_disk', 'scsi0')
        size = re.search(r'(?:^|,)size=(\d+(?:\.\d+)?)([GMT])(?:,|$)', current.get(disk, ''))
        if not size:
            raise P.ProvisionError('Cannot determine the template root disk size')
        gib = float(size[1]) * {'M': 1/1024, 'G': 1, 'T': 1024}[size[2]]
        if spec['disk_gib'] < gib:
            raise P.ProvisionError('The plan would shrink a template disk; refused')
        if spec['disk_gib'] > gib:
            self.wait(self.request('PUT', self.path(name) + '/resize', {'disk': disk, 'size': str(spec['disk_gib']) + 'G'}))
        self.wait(self.request('PUT', self.path(name) + '/config', {'tags': marker + ';' + sig + ';configured'}))
        return name

    def start(self, name):
        self.owned(name)
        if self.request('GET', self.path(name) + '/status/current')['status'] != 'running':
            self.wait(self.request('POST', self.path(name) + '/status/start', {}))

    def stop(self, name):
        self.owned(name)
        if self.request('GET', self.path(name) + '/status/current')['status'] == 'running':
            self.wait(self.request('POST', self.path(name) + '/status/shutdown', {'timeout': 120}))

    def delete(self, name):
        self.owned(name)
        if self.request('GET', self.path(name) + '/status/current')['status'] != 'stopped':
            raise P.ProvisionError('Shut down the VM before deleting it')
        self.wait(self.request('DELETE', self.path(name)))

    def snapshot(self, name, snapshot):
        self.owned(name)
        self.wait(self.request('POST', self.path(name) + '/snapshot', {'snapname': snapshot, 'vmstate': 0}))

    def console(self, name):
        self.owned(name)
        return {'url': self.options['url'].rstrip('/') + '/?console=kvm&vmid=' + str(name) + '&node=' + self.options['node'], 'kind': 'Proxmox web console; sign in separately'}

    def guest_keys(self, name):
        self.owned(name)
        result = self.request('POST', self.path(name) + '/agent/exec', {'command': ['/bin/cat', '/etc/ssh/ssh_host_ed25519_key.pub']})
        return self.exec_result(name, result['pid'])

    def exec_result(self, name, pid):
        for _ in range(60):
            result = self.request('GET', self.path(name) + '/agent/exec-status?pid=' + str(int(pid)))
            if result.get('exited'):
                if result.get('exitcode') != 0:
                    raise P.ProvisionError('Guest agent could not read its SSH public key')
                return result.get('out-data', '').strip()
            time.sleep(1)
        raise P.ProvisionError('Guest agent did not answer')


class KVM(Provider):
    def call(self, operation, **values):
        source = Path(__file__).with_name('vmhost.py').read_text()
        target = self.options.get('target')
        request = dict(operation=operation, owner=self.owner, uri=self.options.get('uri', 'qemu:///system' if target else 'qemu:///session'), **values)
        remote = (['sudo', '-n'] if self.options.get('sudo') else []) + ['python3', '-c', source]
        if not target and self.options.get('sudo'):
            raise P.ProvisionError('Local providers never run desktop sudo; configure libvirt access first')
        argv = P.ssh_args(target) + [shlex.join(remote)] if target else ['python3', '-c', source]
        try:
            return json.loads(P.run(argv, P.dump(request)))
        except P.ProvisionError:
            raise P.ProvisionError('KVM ' + operation + ' failed; check host access, ownership and prerequisites') from None

    def list(self): return self.call('list')
    def storage(self): return self.call('storage')
    def create(self, spec): return self.call('create', spec=spec, fingerprint=fingerprint(spec))
    def start(self, name): return self.call('start', name=str(name))
    def stop(self, name): return self.call('stop', name=str(name))
    def delete(self, name): return self.call('delete', name=str(name))
    def snapshot(self, name, snapshot): return self.call('snapshot', name=str(name), snapshot=snapshot)
    def console(self, name):
        result = self.call('console', name=str(name))
        target = self.options.get('target')
        if target:
            remote = (['sudo', '-n'] if self.options.get('sudo') else []) + ['virsh', '-c', self.options.get('uri', 'qemu:///system'), 'console', str(name)]
            result['command'] = shlex.join(P.ssh_args(target)[:-1] + ['-t', target['ssh'], shlex.join(remote)])
        return result
    def guest_keys(self, name): return self.call('guest_keys', name=str(name))


register('proxmox', Proxmox)
register('kvm', KVM)
