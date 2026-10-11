"""Sent over authenticated SSH to a libvirt host. JSON stdin/stdout, no desktop sudo."""
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as X


def run(args):
    return subprocess.check_output(args, stderr=subprocess.DEVNULL, text=True)


def main(q):
    import libvirt
    if q['uri'] not in ('qemu:///session', 'qemu:///system'): raise ValueError('Use an explicit local QEMU URI on the selected host')
    if os.geteuid() != 0:
        if q['uri'] == 'qemu:///system':
            daemon = 'virtqemud' if Path('/run/libvirt/virtqemud-sock').exists() else 'libvirtd'
            config = Path('/etc/libvirt/' + daemon + '.conf').read_text()
            lines = '\n'.join(line.split('#', 1)[0] for line in config.splitlines())
            if not re.search(r'^\s*auth_unix_rw\s*=\s*["\']none["\']\s*$', lines, re.M) or re.search(r'access_drivers\s*=\s*\[[^\]]*polkit', lines, re.S):
                raise ValueError('System libvirt needs preconfigured socket access without interactive authentication')
        else:
            config_home = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config')))
            for daemon in ('virtqemud', 'libvirtd'):
                file = config_home / 'libvirt' / (daemon + '.conf')
                if file.exists() and re.search(r'^(?!\s*#).*polkit', file.read_text(), re.M):
                    raise ValueError('Session libvirt must not use interactive authentication')
    # Never resolve an alias or collect credentials through a terminal or desktop agent.
    connection = libvirt.openAuth(q['uri'], [[libvirt.VIR_CRED_AUTHNAME, libvirt.VIR_CRED_PASSPHRASE, libvirt.VIR_CRED_EXTERNAL], lambda credentials, data: -1, None], libvirt.VIR_CONNECT_NO_ALIASES)
    op, owner = q['operation'], q.get('owner', '')
    if op == 'list':
        rows = []
        for d in connection.listAllDomains():
            xml = X.fromstring(d.XMLDesc())
            rows.append({'name': d.name(), 'status': 'running' if d.isActive() else 'stopped',
                         'owner': xml.findtext('description', ''), 'cpu': d.info()[3], 'ram_mib': d.info()[1] // 1024})
        return rows
    if op == 'storage':
        return [{'storage': p.name(), 'type': X.fromstring(p.XMLDesc()).get('type'), 'active': bool(p.isActive()),
                 'total': p.info()[1], 'avail': p.info()[3], 'redundancy': 'unknown', 'health': 'inspect host RAID'} for p in connection.listAllStoragePools()]
    if not owner:
        raise ValueError('Ownership ID required')
    if not re.fullmatch(r'[a-z0-9]{8,24}', owner): raise ValueError('Invalid ownership ID')
    if op == 'create':
        s = q['spec']
        if not re.fullmatch(r'[a-z][a-z0-9-]{0,40}', s['name']): raise ValueError('Invalid VM name')
        marker = 'bromigos:' + owner + ':' + q['fingerprint']
        existing = next((d for d in connection.listAllDomains() if d.name() == s['name']), None)
        if existing:
            if X.fromstring(existing.XMLDesc()).findtext('description') != marker:
                raise ValueError('Existing VM belongs to another plan or has changed')
            return s['name']
        pool = connection.storagePoolLookupByName(s['storage'])
        pool_xml = X.fromstring(pool.XMLDesc())
        if pool_xml.get('type') not in ('dir', 'fs', 'netfs') or not pool.isActive():
            raise ValueError('Choose an active file-backed storage pool')
        root = Path(pool_xml.findtext('target/path')).resolve()
        folder = root / ('bromigos-' + owner + '-' + s['name'])
        if folder.exists():
            raise ValueError('Unfinished allocation found; inspect it instead of overwriting')
        image = Path(s['image']).resolve()
        if not image.is_file() or image.is_relative_to(folder):
            raise ValueError('Choose an existing cloud image')
        size = json.loads(run(['qemu-img', 'info', '--output=json', str(image)]))['virtual-size']
        if s['disk_gib'] * 2**30 < size:
            raise ValueError('Shrinking an image is refused')
        folder.mkdir(mode=0o755)
        # A full copy avoids making a running guest depend on a mutable backing image.
        run(['qemu-img', 'convert', '-f', 'qcow2', '-O', 'qcow2', str(image), str(folder / 'root.qcow2')])
        run(['qemu-img', 'resize', str(folder / 'root.qcow2'), str(s['disk_gib']) + 'G'])
        (folder / 'user-data').write_text('#cloud-config\n' + json.dumps({'hostname': s['name'], 'manage_etc_hosts': True,
            'users': [{'name': s['user'], 'sudo': 'ALL=(ALL) NOPASSWD:ALL', 'shell': '/bin/bash', 'ssh_authorized_keys': [s['ssh_public_key']]}],
            'package_update': True, 'packages': ['qemu-guest-agent', 'python' if s.get('distribution') == 'arch' else 'python3', 'curl', 'iptables'],
            'runcmd': [['systemctl', 'enable', '--now', 'qemu-guest-agent']]}))
        (folder / 'meta-data').write_text(json.dumps({'instance-id': owner + '-' + s['name'], 'local-hostname': s['name']}))
        network = {'version': 2, 'ethernets': {'primary': {'match': {'macaddress': s['mac']}, 'set-name': 'ens3',
            'addresses': [s['address']], 'routes': [{'to': 'default', 'via': s['gateway']}], 'nameservers': {'addresses': s['dns']}}}}
        (folder / 'network').write_text(json.dumps(network))
        run(['cloud-localds', '--network-config=' + str(folder / 'network'), str(folder / 'seed.iso'), str(folder / 'user-data'), str(folder / 'meta-data')])
        xml = X.Element('domain', type='kvm')
        X.SubElement(xml, 'name').text = s['name']
        X.SubElement(xml, 'description').text = marker
        X.SubElement(xml, 'memory', unit='MiB').text = str(s['ram_mib'])
        X.SubElement(xml, 'vcpu').text = str(s['cpu'])
        os_xml = X.SubElement(xml, 'os'); X.SubElement(os_xml, 'type', arch='x86_64').text = 'hvm'
        X.SubElement(os_xml, 'boot', dev='hd')
        X.SubElement(xml, 'cpu', mode='host-passthrough')
        features = X.SubElement(xml, 'features'); X.SubElement(features, 'acpi'); X.SubElement(features, 'apic')
        devices = X.SubElement(xml, 'devices')
        # Minimal cloud kernels can omit SATA drivers. Expose the seed through
        # virtio too, so cloud-init can find its cidata filesystem on first boot.
        for filename, device, target, fmt in [('root.qcow2', 'disk', 'vda', 'qcow2'), ('seed.iso', 'disk', 'vdb', 'raw')]:
            disk = X.SubElement(devices, 'disk', type='file', device=device)
            X.SubElement(disk, 'driver', name='qemu', type=fmt)
            X.SubElement(disk, 'source', file=str(folder / filename))
            X.SubElement(disk, 'target', dev=target, bus='virtio')
            if filename == 'seed.iso': X.SubElement(disk, 'readonly')
        iface = X.SubElement(devices, 'interface', type='network' if s.get('network') else 'bridge')
        X.SubElement(iface, 'source', **({'network': s['network']} if s.get('network') else {'bridge': s['bridge']}))
        X.SubElement(iface, 'model', type='virtio'); X.SubElement(iface, 'mac', address=s['mac'])
        if s.get('vlan'):
            vlan = X.SubElement(iface, 'vlan'); X.SubElement(vlan, 'tag', id=str(s['vlan']))
        channel = X.SubElement(devices, 'channel', type='unix')
        X.SubElement(channel, 'target', type='virtio', name='org.qemu.guest_agent.0')
        X.SubElement(devices, 'console', type='pty')
        X.SubElement(devices, 'serial', type='pty')
        if s.get('gpu_pci'):
            domain, bus, slot, function = s['gpu_pci']
            device = X.SubElement(devices, 'hostdev', mode='subsystem', type='pci', managed='yes')
            source = X.SubElement(device, 'source')
            X.SubElement(source, 'address', domain=domain, bus=bus, slot=slot, function=function)
        d = connection.defineXML(X.tostring(xml, encoding='unicode'))
        return d.name()
    d = connection.lookupByName(q['name'])
    xml = X.fromstring(d.XMLDesc())
    if not xml.findtext('description', '').startswith('bromigos:' + owner + ':'):
        raise ValueError('Refusing an unrelated VM')
    if op == 'start':
        if not d.isActive(): d.create()
    elif op == 'stop':
        if d.isActive():
            d.shutdown()
            for _ in range(120):
                if not d.isActive(): break
                time.sleep(1)
            else: raise ValueError('Guest did not shut down; force stop is not automatic')
    elif op == 'delete':
        if d.isActive(): raise ValueError('Shut down before deleting')
        disk = Path(xml.find("devices/disk[@device='disk']/source").get('file')).resolve()
        if disk.parent.name != 'bromigos-' + owner + '-' + d.name():
            raise ValueError('Unrecognised disk; refusing removal')
        d.undefineFlags(libvirt.VIR_DOMAIN_UNDEFINE_SNAPSHOTS_METADATA)
        # Only known files from this allocation; never remove a pool or arbitrary path.
        for filename in ('root.qcow2', 'seed.iso', 'user-data', 'meta-data', 'network'):
            (disk.parent / filename).unlink(missing_ok=True)
        disk.parent.rmdir()
    elif op == 'snapshot':
        if d.isActive(): raise ValueError('Shut down before a disk-only snapshot')
        snapshot = X.Element('domainsnapshot'); X.SubElement(snapshot, 'name').text = q['snapshot']
        X.SubElement(snapshot, 'memory', snapshot='no')
        disks = X.SubElement(snapshot, 'disks')
        X.SubElement(disks, 'disk', name='vda', snapshot='internal')
        X.SubElement(disks, 'disk', name='vdb', snapshot='no')
        d.snapshotCreateXML(X.tostring(snapshot, encoding='unicode'))
    elif op == 'console':
        return {'kind': 'serial', 'command': 'virsh -c ' + q['uri'] + ' console ' + d.name()}
    elif op == 'guest_keys':
        import base64
        import libvirt_qemu
        result = json.loads(libvirt_qemu.qemuAgentCommand(d, json.dumps({'execute': 'guest-exec', 'arguments': {'path': '/bin/cat',
            'arg': ['/etc/ssh/ssh_host_ed25519_key.pub'], 'capture-output': True}}), 20, 0))['return']
        for _ in range(30):
            status = json.loads(libvirt_qemu.qemuAgentCommand(d, json.dumps({'execute': 'guest-exec-status', 'arguments': {'pid': result['pid']}}), 20, 0))['return']
            if status.get('exited'):
                if status.get('exitcode') != 0: raise ValueError('Cannot read guest public key')
                return base64.b64decode(status['out-data']).decode().strip()
            time.sleep(1)
        raise ValueError('Guest agent timed out')
    else:
        raise ValueError('Unknown operation')
    return {'ok': True}


if __name__ == '__main__':
    try:
        print(json.dumps(main(json.load(sys.stdin))))
    except Exception:
        # libvirt errors can contain local paths. No raw provider payloads in logs.
        print('VM host operation failed; inspect access, ownership and prerequisites', file=sys.stderr)
        sys.exit(1)
