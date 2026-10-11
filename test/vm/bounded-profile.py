"""Explicit small, short-retention monitoring fixture; never a production preset."""
import json
import re
from pathlib import Path


def catalog(source, destination):
    text = Path(source).read_text()
    sizes = {'kubernetes': 1.0, 'prometheus': .75, 'grafana': .5, 'loki': .5, 'alertmanager': .125, 'argocd': .5, 'vault': .25}
    text = re.sub(r'ram_headroom_gib = \d+', 'ram_headroom_gib = 0.5', text)
    for name, memory in sizes.items():
        pattern = r'(\[service\.' + name + r'\]\n)(.*?)(?=\n\[|\Z)'
        def replace(match):
            body = re.sub(r'cpu = \d+', 'cpu = 1', match[2])
            body = re.sub(r'ram_gib = [\d.]+', 'ram_gib = ' + str(memory), body)
            return match[1] + body
        text = re.sub(pattern, replace, text, flags=re.S)
    Path(destination).write_text(text)


def trim(files):
    path = 'helm/monitoring/values.yaml'
    if path not in files: return
    values = json.loads(files[path])
    values['defaultRules']['create'] = False
    values['grafana'].setdefault('sidecar', {}).setdefault('dashboards', {})['enabled'] = False
    prom = values['prometheus']['prometheusSpec']
    prom.update(retention='2h', retentionSize='512MB', resources={'requests': {'memory': '256Mi', 'cpu': '50m'}, 'limits': {'memory': '768Mi'}})
    values['grafana'].update(defaultDashboardsEnabled=False, resources={'requests': {'memory': '128Mi', 'cpu': '25m'}, 'limits': {'memory': '512Mi'}})
    values['alertmanager']['alertmanagerSpec']['resources'] = {'requests': {'memory': '32Mi', 'cpu': '10m'}, 'limits': {'memory': '128Mi'}}
    nested = json.loads(files['plan.json'])['target'].get('jump')
    if nested:
        worker = {'kubernetes.io/hostname': 'worker-one'}
        prom['nodeSelector'] = worker
        values['grafana']['nodeSelector'] = worker
        values['alertmanager']['alertmanagerSpec']['nodeSelector'] = worker
        values.setdefault('prometheusOperator', {})['nodeSelector'] = worker
        values.setdefault('kube-state-metrics', {})['nodeSelector'] = worker
    files[path] = json.dumps(values, indent=2) + '\n'
    path = 'helm/loki/values.yaml'; values = json.loads(files[path])
    if nested: values['singleBinary']['nodeSelector'] = worker
    values['singleBinary']['resources'] = {'requests': {'memory': '128Mi', 'cpu': '25m'}, 'limits': {'memory': '512Mi'}}
    values['loki']['limits_config'] = {'retention_period': '24h'}
    files[path] = json.dumps(values, indent=2) + '\n'


def nested_budget(nodes):
    memory = 4096 + sum(node['vm']['ram_mib'] for node in nodes)
    cpus = 1 + sum(node['vm']['cpu'] for node in nodes)
    if memory > 10 * 1024 or cpus > 4:
        raise RuntimeError('Nested fixture exceeds 10 GiB / four CPUs including its parent')
