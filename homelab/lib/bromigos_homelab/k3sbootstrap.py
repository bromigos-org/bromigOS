"""Wait for k3s bootstrap CRDs without changing their readiness or deleting data."""
import json
from pathlib import Path
import subprocess
import sys
import time

NAMES = ('addons.k3s.cattle.io', 'etcdsnapshotfiles.k3s.cattle.io',
         'helmchartconfigs.helm.cattle.io', 'helmcharts.helm.cattle.io')


def reconcile(run=subprocess.run, clock=time.monotonic, sleep=time.sleep, timeout=180):
    started = clock()
    requested = set()
    while clock() - started < timeout:
        result = run(['/usr/local/bin/k3s', 'kubectl', 'get', 'crds', '-o', 'json'],
                     capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            rows = {r['metadata']['name']: r for r in json.loads(result.stdout)['items']}
            conditions = {name: {c['type']: c['status'] for c in rows.get(name, {}).get('status', {}).get('conditions', [])} for name in NAMES}
            if all(conditions[name].get('Established') == 'True' for name in NAMES):
                return bool(requested)
            if clock() - started >= 30:
                for name in NAMES:
                    if name not in requested and conditions[name].get('NamesAccepted') == 'True' and conditions[name].get('Established') == 'False':
                        update = run(['/usr/local/bin/k3s', 'kubectl', 'annotate', 'crd', name,
                                      'bromigos.org/bootstrap-reconcile=true', '--overwrite'],
                                     capture_output=True, text=True, timeout=15)
                        if update.returncode == 0: requested.add(name)
        sleep(2)
    raise RuntimeError('k3s bootstrap definitions did not become ready within three minutes')


if __name__ == '__main__':
    marker = Path(sys.argv[1])
    if marker.parent != Path('/etc/rancher/k3s') or not marker.name.startswith('bromigos-') or not marker.is_file():
        raise SystemExit('Refusing bootstrap changes on an unowned k3s installation')
    try:
        print('bootstrap-reconciled' if reconcile() else 'bootstrap-ready')
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired):
        raise SystemExit('k3s bootstrap check failed; inspect the owned cluster before retrying') from None
