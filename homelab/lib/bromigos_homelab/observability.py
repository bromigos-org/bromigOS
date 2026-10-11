"""Mandatory monitoring plans and read-only access through the explicit lab target."""
import contextlib
import json
from pathlib import Path
import secrets
import shlex
import socket
import subprocess
import time
import urllib.parse
import urllib.request

SERVICES = ('prometheus', 'grafana', 'loki', 'alertmanager')
STACK_VERSION = '92.3.0'
LOKI_VERSION = '7.3.0'
ALLOY_VERSION = '1.13.1'
IMAGES = {'prometheus': 'prom/prometheus:v3.15.0', 'alertmanager': 'prom/alertmanager:v0.34.1',
          'node-exporter': 'prom/node-exporter:v1.12.1', 'blackbox': 'prom/blackbox-exporter:v0.29.0',
          'grafana': 'grafana/grafana:13.2.3', 'loki': 'grafana/loki:3.7.8', 'alloy': 'grafana/alloy:v1.20.1'}
PORTS = {'prometheus': 9090, 'alertmanager': 9093, 'grafana': 3000, 'loki': 3100}
CLUSTER_NAMES = {'prometheus': 'lab-monitoring-prometheus', 'alertmanager': 'lab-monitoring-alertmanager',
                 'grafana': 'lab-grafana', 'loki': 'lab-loki'}


# Capture Helm output in memory: notes and errors may contain credentials.
# Only fixed diagnostic words leave this wrapper, even when Ansible reports a failure.
HELM_RUNNER = """import os, subprocess, sys
env = dict(os.environ, HELM_DEBUG='false')
version = subprocess.run(['helm', 'version', '--short'], capture_output=True, text=True, env=env)
args = sys.argv[1:]
if version.returncode:
    print('bromigos-helm: version check failed'); sys.exit(1)
if version.stdout.strip().startswith('v4.'):
    args += ['--server-side=false']
result = subprocess.run(args, capture_output=True, text=True, env=env)
if result.returncode:
    output = (result.stdout + result.stderr).lower()
    reasons = [('conflict', 'ownership conflict'), ('another operation', 'release busy'),
               ('immutable', 'immutable field'), ('already exists', 'resource exists'),
               ('forbidden', 'permission refused'), ('timed out', 'readiness timeout'),
               ('deadline exceeded', 'readiness timeout'), ('connection refused', 'connection refused')]
    category = next((label for pattern, label in reasons if pattern in output), 'upgrade failed')
    print('bromigos-helm: ' + category)
else:
    print('bromigos-helm: applied')
sys.exit(result.returncode)
"""


def helm_command(argv):
    return ['python3', '-c', HELM_RUNNER] + argv


def dashboard(name, expressions):
    return {'uid': 'lab-' + name, 'title': 'Lab ' + name, 'schemaVersion': 39, 'version': 1,
            'refresh': '30s', 'time': {'from': 'now-1h', 'to': 'now'}, 'panels': [
                {'id': i + 1, 'title': title, 'type': 'timeseries', 'datasource': {'type': 'prometheus', 'uid': 'lab-prometheus'},
                 'gridPos': {'x': 0, 'y': i * 8, 'w': 24, 'h': 8}, 'targets': [{'refId': 'A', 'expr': expr}]} for i, (title, expr) in enumerate(expressions)]}


def dashboards():
    return {name: dashboard(name, rows) for name, rows in {
        'nodes': [('CPU use', '100*(1-avg by(instance)(rate(node_cpu_seconds_total{mode="idle"}[5m])))'),
                  ('Available memory', 'node_memory_MemAvailable_bytes'), ('Available disk', 'node_filesystem_avail_bytes')],
        'kubernetes': [('Ready nodes', 'kube_node_status_condition{condition="Ready",status="true"}'), ('Pending pods', 'sum(kube_pod_status_phase{phase="Pending"})')],
        'gpu': [('GPU use', 'DCGM_FI_DEV_GPU_UTIL'), ('GPU memory', 'DCGM_FI_DEV_FB_USED')],
        'apps': [('Scrape targets', 'up'), ('Service probes', 'probe_success'), ('Recent backup', 'lab_backup_last_success_timestamp_seconds')],
    }.items()}


def rules(cluster=False, backup=False):
    rows = [('NodeDown', 'up{job=~".*node.*"} == 0', '2m', 'A node exporter is unreachable'),
            ('DiskFilling', 'node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"}/node_filesystem_size_bytes < 0.15', '10m', 'A disk has less than 15 percent free'),
            ('ServiceDown', 'probe_success == 0', '2m', 'A provisioned service does not answer'),
            ('CertificateExpiring', 'probe_ssl_earliest_cert_expiry - time() < 14*86400', '10m', 'A certificate expires within 14 days')]
    if cluster:
        rows += [('PodCrashlooping', 'max_over_time(kube_pod_container_status_waiting_reason{reason="CrashLoopBackOff"}[5m]) == 1', '5m', 'A pod is crashlooping')]
    if backup:
        expr = 'time()-lab_backup_last_success_timestamp_seconds > 30*3600 or absent(lab_backup_last_success_timestamp_seconds)'
        if cluster:
            expr = 'time()-kube_cronjob_status_last_successful_time{cronjob="restic"} > 30*3600 or absent(kube_cronjob_status_last_successful_time{cronjob="restic"})'
        rows += [('BackupStale', expr, '10m', 'No successful backup within 30 hours')]
    return [{'alert': name, 'expr': expr, 'for': duration, 'labels': {'severity': 'warning'}, 'annotations': {'summary': summary}} for name, expr, duration, summary in rows]


def plan(files, state, roles):
    from . import provision as P
    if not any(s in state['selected'] for s in SERVICES): return
    cluster = 'kubernetes' in state['selected'] or state['target']['kind'] == 'cluster'
    state['observability'] = {'mode': 'cluster' if cluster else 'host', 'storage_class': state.get('storage_class', '')}
    if cluster and state['target']['kind'] == 'ssh':
        state['observability']['migration_note'] = 'Stop any prior owned single-box monitoring containers; keep their volumes. Kubernetes monitoring uses new persistent volumes.'
    for name, doc in dashboards().items(): files['monitoring/dashboards/' + name + '.json'] = P.dump(doc)
    alert_rules = {'groups': [{'name': 'lab', 'rules': rules(cluster, 'restic' in state['selected'])}]}
    if state.get('domain'):
        # Caddy's internal leaf certificates last 12 hours and renew automatically.
        for rule in alert_rules['groups'][0]['rules']:
            if rule['alert'] == 'CertificateExpiring':
                rule.update(expr='probe_ssl_earliest_cert_expiry - time() < 3600', annotations={'summary': 'A local certificate expires within one hour'})
    files['monitoring/rules.json'] = P.dump(alert_rules)
    if cluster:
        cluster_plan(files, state, roles, alert_rules)
    else:
        host_plan(files, state, roles, alert_rules)
    files['plan.json'] = P.dump(state)
    if cluster:
        box = state['target']['kind'] == 'ssh'
        files['ansible/playbooks/bootstrap.json'] = P.dump([{'hosts': 'all', 'become': box, 'gather_facts': False, 'roles': [r for r in ('k3s', 'helm') if r in roles]}])


def probes(state, cluster=False):
    urls = []
    ports = {'caddy': (80, '/'), 'homepage': (3000, '/'), 'netdata': (19999, '/api/v1/info'),
             'hermes': (8642, '/health'), 'openclaw': (18789, '/healthz'), 'vault': (8200, '/v1/sys/health'), 'argocd': (80, '/healthz')}
    for svc in state['selected']:
        if svc not in ports: continue
        port, path = ports[svc]
        if cluster:
            if svc in ('caddy', 'homepage', 'netdata'):
                if state['target']['kind'] == 'ssh':
                    if svc == 'homepage' and 'caddy' in state['selected']: continue
                    host = state.get('listen_address', '127.0.0.1')
                    if svc == 'netdata':
                        if 'caddy' in state['selected']: port, path = 80, '/netdata/api/v1/info'
                else: host = svc + '.lab-core.svc'
            elif svc in ('hermes', 'openclaw'):
                host = '127.0.0.1' if state['target']['kind'] == 'ssh' else svc + '.lab-agents.svc'
            else: host = ('argocd-server' if svc == 'argocd' else svc) + '.' + svc + '.svc'
        else:
            host = '127.0.0.1'
            if svc in ('caddy', 'netdata'): host = state.get('listen_address', '127.0.0.1')
            if svc == 'homepage' and 'caddy' in state['selected']: continue
            if svc == 'netdata':
                if 'caddy' in state['selected']: port, path = 80, '/netdata/api/v1/info'
        urls.append('http://' + host + ':' + str(port) + path)
    if state.get('domain'): urls.append('https://' + state['domain'])
    return urls


def blackbox_config(state):
    http = {'preferred_ip_protocol': 'ip4'}
    # Caddy's explicitly chosen local HTTPS name has a private certificate authority.
    # This probe measures reach and certificate expiry, not trust in that authority.
    if state.get('domain'): http['tls_config'] = {'insecure_skip_verify': True}
    return {'modules': {'http_2xx': {'prober': 'http', 'timeout': '5s', 'http': http}}}


def service_scrapes(state, cluster=False):
    url = next((u for u in probes(state, cluster) if u.endswith('/api/v1/info')), '')
    if not url: return []
    parsed = urllib.parse.urlsplit(url)
    job = {'job_name': 'netdata', 'honor_labels': True, 'scheme': parsed.scheme,
           'metrics_path': parsed.path.replace('/info', '/allmetrics'), 'params': {'format': ['prometheus']},
           'static_configs': [{'targets': [parsed.netloc]}]}
    if state.get('domain'): job['tls_config'] = {'insecure_skip_verify': True}
    return [job]


def host_plan(files, state, roles, alert_rules):
    from . import provision as P
    target = state['target']
    prom = {'global': {'scrape_interval': '15s', 'evaluation_interval': '15s'}, 'rule_files': ['/etc/lab/rules.json'],
        'alerting': {'alertmanagers': [{'static_configs': [{'targets': ['127.0.0.1:9093']}]}]},
        'scrape_configs': [{'job_name': name, 'static_configs': [{'targets': ['127.0.0.1:' + str(port)]}]} for name, port in
            [('prometheus', 9090), ('node-exporter', 9100), ('loki', 3100), ('alertmanager', 9093), ('grafana', 3001), ('blackbox', 9115), ('alloy', 12345)]]}
    if probes(state):
        prom['scrape_configs'] += service_scrapes(state)
        prom['scrape_configs'].append({'job_name': 'lab-services', 'metrics_path': '/probe', 'params': {'module': ['http_2xx']},
            'static_configs': [{'targets': probes(state)}], 'relabel_configs': [{'source_labels': ['__address__'], 'target_label': '__param_target'},
                {'source_labels': ['__param_target'], 'target_label': 'instance'}, {'target_label': '__address__', 'replacement': '127.0.0.1:9115'}]})
    files['monitoring/config/rules.json'] = files.pop('monitoring/rules.json')
    files['monitoring/config/prometheus.json'] = P.dump(prom)
    files['monitoring/config/alertmanager.json'] = P.dump({'route': {'receiver': 'local', 'group_wait': '10s'}, 'receivers': [{'name': 'local'}]})
    files['monitoring/config/blackbox.json'] = P.dump(blackbox_config(state))
    files['monitoring/config/loki.json'] = P.dump({'auth_enabled': False, 'server': {'http_listen_port': 3100, 'http_listen_address': '127.0.0.1'}, 'common': {
        'path_prefix': '/loki', 'replication_factor': 1, 'ring': {'kvstore': {'store': 'inmemory'}}, 'storage': {'filesystem': {'chunks_directory': '/loki/chunks', 'rules_directory': '/loki/rules'}}},
        'schema_config': {'configs': [{'from': '2024-01-01', 'store': 'tsdb', 'object_store': 'filesystem', 'schema': 'v13', 'index': {'prefix': 'index_', 'period': '24h'}}]},
        'limits_config': {'retention_period': '168h'}, 'compactor': {'retention_enabled': True, 'delete_request_store': 'filesystem'}, 'analytics': {'reporting_enabled': False}})
    files['monitoring/config/datasources/lab.yaml'] = P.dump({'apiVersion': 1, 'datasources': [
        {'name': 'Lab Prometheus', 'uid': 'lab-prometheus', 'type': 'prometheus', 'url': 'http://127.0.0.1:9090', 'access': 'proxy', 'isDefault': True},
        {'name': 'Lab Loki', 'uid': 'lab-loki', 'type': 'loki', 'url': 'http://127.0.0.1:3100', 'access': 'proxy'}]})
    files['monitoring/config/dashboard-providers/lab.yaml'] = P.dump({'apiVersion': 1, 'providers': [{'name': 'Lab', 'type': 'file', 'options': {'path': '/var/lib/grafana/dashboards'}}]})
    files['monitoring/config/config.alloy'] = 'loki.source.journal "system" {\n path = "/var/log/journal"\n labels = {job = "system-journal"}\n forward_to = [loki.write.lab.receiver]\n}\nloki.write "lab" { endpoint { url = "http://127.0.0.1:3100/loki/api/v1/push" } }\n'
    containers = {}
    for name, image in IMAGES.items():
        containers[name] = {'image': image, 'restart': 'unless-stopped', 'network_mode': 'host'}
    # Bind each host-network listener to loopback; containers share no Docker socket.
    containers['prometheus'].update(command=['--config.file=/etc/lab/prometheus.json', '--storage.tsdb.retention.time=15d', '--web.listen-address=127.0.0.1:9090'],
        volumes=['./config:/etc/lab:ro', 'prometheus:/prometheus'])
    containers['alertmanager'].update(command=['--config.file=/etc/lab/alertmanager.json', '--web.listen-address=127.0.0.1:9093', '--cluster.listen-address='], volumes=['./config:/etc/lab:ro', 'alertmanager:/alertmanager'])
    containers['loki'].update(command=['-config.file=/etc/lab/loki.json'], volumes=['./config:/etc/lab:ro', 'loki:/loki'])
    containers['grafana'].update(environment={'GF_SERVER_HTTP_ADDR': '127.0.0.1', 'GF_SERVER_HTTP_PORT': '3001', 'GF_SECURITY_ADMIN_PASSWORD__FILE': '/run/secrets/admin', 'GF_USERS_ALLOW_SIGN_UP': 'false', 'GF_ANALYTICS_REPORTING_ENABLED': 'false'},
        volumes=['./grafana-password:/run/secrets/admin:ro', 'grafana:/var/lib/grafana', './dashboards:/var/lib/grafana/dashboards:ro',
                 './config/datasources:/etc/grafana/provisioning/datasources:ro', './config/dashboard-providers:/etc/grafana/provisioning/dashboards:ro'])
    containers['blackbox'].update(command=['--config.file=/etc/lab/blackbox.json', '--web.listen-address=127.0.0.1:9115'], volumes=['./config:/etc/lab:ro'])
    containers['node-exporter'].update(command=['--web.listen-address=127.0.0.1:9100', '--path.rootfs=/host', '--collector.textfile.directory=/textfile'], pid='host', volumes=['/:/host:ro,rslave', './textfile:/textfile:ro'])
    containers['alloy'].update(user='0', command=['run', '/etc/lab/config.alloy', '--storage.path=/data', '--server.http.listen-addr=127.0.0.1:12345'], volumes=['./config:/etc/lab:ro', '/var/log/journal:/var/log/journal:ro', 'alloy:/data'])
    if state['inventory'].get('gpu') == 'nvidia':
        containers['dcgm'] = {'image': 'nvcr.io/nvidia/k8s/dcgm-exporter:4.6.1-4.8.4-distroless', 'restart': 'unless-stopped', 'network_mode': 'host', 'runtime': 'nvidia', 'cap_add': ['SYS_ADMIN'], 'environment': {'NVIDIA_VISIBLE_DEVICES': 'all', 'DCGM_EXPORTER_LISTEN': '127.0.0.1:9400'}}
        prom['scrape_configs'].append({'job_name': 'gpu', 'static_configs': [{'targets': ['127.0.0.1:9400']}]})
        files['monitoring/config/prometheus.json'] = P.dump(prom)
    files['monitoring/compose.yaml'] = P.dump({'services': containers, 'volumes': {n: {} for n in ('prometheus', 'alertmanager', 'loki', 'grafana', 'alloy')}})
    roles.append('monitoring')
    packages = {'debian': ['docker.io', 'docker-compose'], 'ubuntu': ['docker.io', 'docker-compose'], 'fedora': ['moby-engine', 'docker-compose'], 'arch': ['docker', 'docker-compose']}[state['inventory']['distribution']]
    tasks = [P.task('Install monitoring engine', 'ansible.builtin.package', {'name': packages, 'state': 'present', 'update_cache': True}),
        P.task('Keep container engine running', 'ansible.builtin.systemd', {'name': 'docker', 'state': 'started', 'enabled': True}),
        P.task('Copy reviewed monitoring settings', 'ansible.builtin.copy', {'src': '{{ playbook_dir }}/../../monitoring/', 'dest': '/opt/bromigos-monitoring/', 'mode': '0644', 'directory_mode': '0755'}, register='monitoring_files'),
        P.task('Create exporter textfile folder', 'ansible.builtin.file', {'path': '/opt/bromigos-monitoring/textfile', 'state': 'directory', 'mode': '0755'}),
        P.task('Start monitoring without removing state', 'ansible.builtin.shell', {'cmd': 'if docker compose version >/dev/null 2>&1; then docker compose -p bromigos-monitoring up -d {{ "--force-recreate" if monitoring_files.changed else "" }}; else docker-compose -p bromigos-monitoring up -d {{ "--force-recreate" if monitoring_files.changed else "" }}; fi', 'chdir': '/opt/bromigos-monitoring'}, changed_when=False)]
    if 'restic' in state['selected']: tasks += backup_tasks(P)
    files['ansible/roles/monitoring/tasks/main.json'] = P.dump(tasks)


def backup_tasks(P):
    script = '#!/bin/sh\nset -eu\nstamp=$(docker exec $(docker ps -q --filter label=com.docker.compose.service=restic --filter label=com.docker.compose.project=bromigos-lab) stat -c %Y /status/last-success)\nprintf "lab_backup_last_success_timestamp_seconds %s\\n" "$stamp" > /opt/bromigos-monitoring/textfile/backup.prom.tmp\nmv /opt/bromigos-monitoring/textfile/backup.prom.tmp /opt/bromigos-monitoring/textfile/backup.prom\n'
    return [P.task('Write backup metric collector', 'ansible.builtin.copy', {'content': script, 'dest': '/opt/bromigos-monitoring/backup-metric', 'mode': '0700'}),
            P.task('Write backup metric service', 'ansible.builtin.copy', {'content': '[Service]\nType=oneshot\nExecStart=/opt/bromigos-monitoring/backup-metric\n', 'dest': '/etc/systemd/system/bromigos-backup-metric.service'}),
            P.task('Write backup metric timer', 'ansible.builtin.copy', {'content': '[Timer]\nOnBootSec=1min\nOnUnitActiveSec=1min\n[Install]\nWantedBy=timers.target\n', 'dest': '/etc/systemd/system/bromigos-backup-metric.timer'}),
            P.task('Start backup metric timer', 'ansible.builtin.systemd', {'name': 'bromigos-backup-metric.timer', 'state': 'started', 'enabled': True, 'daemon_reload': True})]


def cluster_plan(files, state, roles, alert_rules):
    from . import provision as P
    storage = state.get('storage_class') or ('local-path' if state['target']['kind'] == 'ssh' else None)
    pvc = lambda size: {'volumeClaimTemplate': {'metadata': {'annotations': {'helm.sh/resource-policy': 'keep'}}, 'spec': {**({'storageClassName': storage} if storage else {}), 'accessModes': ['ReadWriteOnce'], 'resources': {'requests': {'storage': size}}}}}
    values = {'fullnameOverride': 'lab-monitoring', 'kubeControllerManager': {'enabled': False}, 'kubeScheduler': {'enabled': False},
        'kubeEtcd': {'enabled': False}, 'kubeProxy': {'enabled': False}, 'defaultRules': {'rules': {'etcd': False, 'kubeControllerManager': False, 'kubeSchedulerAlerting': False, 'kubeSchedulerRecording': False, 'kubeProxy': False}},
        'prometheus': {'prometheusSpec': {'retention': '15d', 'storageSpec': pvc('20Gi'),
            'additionalScrapeConfigs': [{'job_name': 'blackbox', 'static_configs': [{'targets': ['lab-blackbox:9115']}]}],
            'serviceMonitorSelectorNilUsesHelmValues': False, 'podMonitorSelectorNilUsesHelmValues': False,
            'resources': {'requests': {'memory': '512Mi', 'cpu': '200m'}}}},
        'alertmanager': {'alertmanagerSpec': {'storage': pvc('2Gi')}},
        'grafana': {'fullnameOverride': 'lab-grafana', 'admin': {'existingSecret': 'lab-grafana-admin', 'userKey': 'user', 'passwordKey': 'password'},
            'service': {'port': PORTS['grafana']},
            'serviceMonitor': {'enabled': True},
            'persistence': {'enabled': True, 'storageClassName': storage, 'size': '5Gi'}, 'defaultDashboardsEnabled': True,
            'sidecar': {'datasources': {'enabled': False}},
            'datasources': {'datasources.yaml': {'apiVersion': 1, 'datasources': [{'name': 'Lab Prometheus', 'uid': 'lab-prometheus', 'type': 'prometheus', 'url': 'http://lab-monitoring-prometheus:9090', 'isDefault': True}, {'name': 'Lab Loki', 'uid': 'lab-loki', 'type': 'loki', 'url': 'http://lab-loki:3100'}]}},
            'dashboardProviders': {'dashboardproviders.yaml': {'apiVersion': 1, 'providers': [{'name': 'lab', 'type': 'file', 'options': {'path': '/var/lib/grafana/dashboards/lab'}}]}},
            'dashboards': {'lab': {name: {'json': P.dump(doc)} for name, doc in dashboards().items()}}},
        'additionalPrometheusRulesMap': {'lab': alert_rules}}
    if probes(state, True):
        values['prometheus']['prometheusSpec']['additionalScrapeConfigs'] += [{'job_name': 'lab-services', 'metrics_path': '/probe', 'params': {'module': ['http_2xx']}, 'static_configs': [{'targets': probes(state, True)}], 'relabel_configs': [
            {'source_labels': ['__address__'], 'target_label': '__param_target'}, {'source_labels': ['__param_target'], 'target_label': 'instance'}, {'target_label': '__address__', 'replacement': 'lab-blackbox:9115'}]}]
    host_netdata = state['target']['kind'] == 'ssh' and 'netdata' in state['selected']
    if host_netdata:
        values['prometheus']['prometheusSpec']['enableRemoteWriteReceiver'] = True
    else:
        values['prometheus']['prometheusSpec']['additionalScrapeConfigs'] += service_scrapes(state, True)
    if state['target']['kind'] == 'ssh' and 'restic' in state['selected']:
        for group in alert_rules['groups']:
            for rule in group['rules']:
                if rule['alert'] == 'BackupStale': rule['expr'] = rules(False, True)[-1]['expr']
        values['prometheus-node-exporter'] = {'extraArgs': ['--collector.textfile.directory=/host/root/opt/bromigos-monitoring/textfile']}
        files['monitoring/rules.json'] = P.dump(alert_rules)
    files['helm/monitoring/values.yaml'] = P.dump(values)
    loki = {'deploymentMode': 'SingleBinary', 'fullnameOverride': 'lab-loki', 'loki': {'auth_enabled': False, 'commonConfig': {'replication_factor': 1},
        'storage': {'type': 'filesystem'}, 'schemaConfig': {'configs': [{'from': '2024-01-01', 'store': 'tsdb', 'object_store': 'filesystem', 'schema': 'v13', 'index': {'prefix': 'index_', 'period': '24h'}}]}},
        'singleBinary': {'replicas': 1, 'persistence': {'storageClass': storage, 'size': '20Gi'}}, 'read': {'replicas': 0}, 'write': {'replicas': 0}, 'backend': {'replicas': 0},
        'gateway': {'enabled': False}, 'chunksCache': {'enabled': False}, 'resultsCache': {'enabled': False}, 'lokiCanary': {'enabled': False}, 'test': {'enabled': False}}
    loki['monitoring'] = {'serviceMonitor': {'enabled': True}}
    files['helm/loki/values.yaml'] = P.dump(loki)
    alloy = {'controller': {'type': 'daemonset', 'tolerations': [{'operator': 'Exists'}]}, 'alloy': {'mounts': {'varlog': True}, 'configMap': {'content':
        'loki.source.journal "system" {\n path = "/var/log/journal"\n labels = {job = "system-journal"}\n forward_to = [loki.write.lab.receiver]\n}\nloki.write "lab" {\n endpoint {\n url = "http://lab-loki.monitoring.svc:3100/loki/api/v1/push"\n }\n}\n'}}}
    if host_netdata:
        # Netdata stays on the box's loopback interface. A pod's loopback is different.
        # Collect on that host and send metrics to the private Prometheus service.
        alloy['controller'].update(hostNetwork=True, dnsPolicy='ClusterFirstWithHostNet',
                                   nodeSelector={'node-role.kubernetes.io/control-plane': 'true'})
        job = service_scrapes(state, True)[0]
        alloy['alloy']['configMap']['content'] += (
            'prometheus.scrape "netdata" {\n'
            ' targets = [{__address__ = ' + json.dumps(job['static_configs'][0]['targets'][0]) + '}]\n'
            ' job_name = "netdata"\n honor_labels = true\n scrape_interval = "15s"\n'
            ' metrics_path = ' + json.dumps(job['metrics_path']) + '\n params = {format = ["prometheus"]}\n'
            ' forward_to = [prometheus.remote_write.lab.receiver]\n}\n'
            'prometheus.remote_write "lab" {\n endpoint {\n'
            ' url = "http://lab-monitoring-prometheus.monitoring.svc:9090/api/v1/write"\n }\n}\n')
    alloy['serviceMonitor'] = {'enabled': True}
    files['helm/alloy/values.yaml'] = P.dump(alloy)
    # Blackbox is a small generic chart, also used for services without a metrics API.
    docs = [{'apiVersion': 'apps/v1', 'kind': 'Deployment', 'metadata': {'name': 'lab-blackbox'}, 'spec': {'replicas': 1, 'selector': {'matchLabels': {'app': 'lab-blackbox'}},
        'template': {'metadata': {'labels': {'app': 'lab-blackbox'}}, 'spec': {'automountServiceAccountToken': False, 'containers': [{'name': 'blackbox', 'image': IMAGES['blackbox'], 'ports': [{'containerPort': 9115}]}]}}}},
        {'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': 'lab-blackbox'}, 'spec': {'selector': {'app': 'lab-blackbox'}, 'ports': [{'port': 9115}]}}]
    pod = docs[0]['spec']['template']['spec']
    pod['volumes'] = [{'name': 'config', 'configMap': {'name': 'lab-blackbox'}}]
    pod['containers'][0].update(args=['--config.file=/etc/lab/config.json'], volumeMounts=[{'name': 'config', 'mountPath': '/etc/lab', 'readOnly': True}])
    docs.append({'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'lab-blackbox'}, 'data': {'config.json': P.dump(blackbox_config(state))}})
    if state['target']['kind'] == 'ssh':
        docs[0]['spec']['template']['spec'].update(hostNetwork=True, dnsPolicy='ClusterFirstWithHostNet', nodeSelector={'node-role.kubernetes.io/control-plane': 'true'})
    files['helm/monitor-extra/Chart.yaml'] = 'apiVersion: v2\nname: lab-monitor-extra\nversion: 0.1.0\n'
    files['helm/monitor-extra/templates/resources.yaml'] = '---\n'.join(P.dump(d) for d in docs)
    charts = [('monitor-extra', None, None, None), ('monitoring', 'https://prometheus-community.github.io/helm-charts', 'kube-prometheus-stack', STACK_VERSION),
              ('loki', 'https://grafana.github.io/helm-charts', 'loki', LOKI_VERSION), ('alloy', 'https://grafana.github.io/helm-charts', 'alloy', ALLOY_VERSION)]
    if state['inventory'].get('gpu') == 'nvidia':
        gpu_values = {'tolerations': [{'operator': 'Exists'}]}
        if state['target']['kind'] == 'ssh':
            gpu_values['runtimeClassName'] = 'nvidia'
            files['helm/nvidia-device-plugin/values.yaml'] = P.dump(gpu_values)
            charts.append(('nvidia-device-plugin', 'https://nvidia.github.io/k8s-device-plugin', 'nvidia-device-plugin', '0.20.1'))
        else:
            gpu_values['affinity'] = {'nodeAffinity': {'requiredDuringSchedulingIgnoredDuringExecution': {'nodeSelectorTerms': [{'matchFields': [{'key': 'metadata.name', 'operator': 'In', 'values': state['inventory']['gpu_nodes']}]}]}}}
        files['helm/dcgm-exporter/values.yaml'] = P.dump({**gpu_values, 'serviceMonitor': {'enabled': True}})
        charts.append(('dcgm-exporter', 'https://nvidia.github.io/dcgm-exporter/helm-charts', 'dcgm-exporter', '4.8.4'))
    roles.append('monitoring')
    box = state['target']['kind'] == 'ssh'
    tasks = []
    if box:
        tasks.append(P.task('Stop prior owned monitoring without deleting volumes', 'ansible.builtin.shell', {'cmd': 'if command -v docker >/dev/null 2>&1 && test -f /opt/bromigos-monitoring/compose.yaml; then containers=$(docker ps -q --filter label=com.docker.compose.project=bromigos-monitoring); if test -n "$containers"; then docker stop $containers; fi; fi'}, changed_when=False))
    if box and 'restic' in state['selected']:
        tasks.append(P.task('Create backup metric folder', 'ansible.builtin.file', {'path': '/opt/bromigos-monitoring/textfile', 'state': 'directory', 'mode': '0755'}))
        tasks += backup_tasks(P)
    if box: tasks.append(P.task('Copy reviewed monitoring charts', 'ansible.builtin.copy', {'src': '{{ playbook_dir }}/../../helm/', 'dest': '/opt/bromigos-lab/helm/', 'mode': '0644'}))
    for release, repo, chart, version in charts:
        path = '/opt/bromigos-lab/helm/' if box else '{{ playbook_dir }}/../../helm/'
        argv = ['helm', 'upgrade', '--install', 'lab-' + release, chart or path + release, '--namespace', 'monitoring', '--create-namespace', '--description', 'bromigos-lab-provision', '--wait', '--timeout', '15m']
        if repo: argv += ['--repo', repo, '--version', version, '--values', path + release + '/values.yaml']
        env = {'KUBECONFIG': '/etc/rancher/k3s/k3s.yaml' if box else state['target']['kubeconfig']}
        if not box: env['HELM_KUBECONTEXT'] = state['target']['context']
        tasks += [P.task('Read monitoring release ownership', 'ansible.builtin.command', {'argv': ['helm', 'status', 'lab-' + release, '-n', 'monitoring', '-o', 'json']}, environment=env, register='existing_release', failed_when=False, changed_when=False),
            P.task('Refuse an unrelated monitoring release', 'ansible.builtin.assert', {'that': ["existing_release.rc != 0 or (existing_release.stdout | from_json).info.description == 'bromigos-lab-provision'"]}),
            P.task('Converge ' + release, 'ansible.builtin.command', {'argv': helm_command(argv)}, environment=env, no_log=False, changed_when=False)]
        if 'argocd' in state['selected']:
            source = {'repoURL': state['git_url'], 'targetRevision': 'HEAD', 'path': 'helm/' + release} if not repo else None
            app = {'apiVersion': 'argoproj.io/v1alpha1', 'kind': 'Application', 'metadata': {'name': 'lab-' + release, 'namespace': 'argocd'}, 'spec': {
                'project': 'default', 'destination': {'server': 'https://kubernetes.default.svc', 'namespace': 'monitoring'}, 'syncPolicy': {'automated': {'selfHeal': True, 'prune': False}, 'syncOptions': ['CreateNamespace=true', 'ServerSideApply=true']}}}
            if source: app['spec']['source'] = source
            else: app['spec']['sources'] = [{'repoURL': repo, 'chart': chart, 'targetRevision': version, 'helm': {'releaseName': 'lab-' + release, 'valueFiles': ['$values/helm/' + release + '/values.yaml']}}, {'repoURL': state['git_url'], 'targetRevision': 'HEAD', 'ref': 'values'}]
            files['gitops/argocd-apps/lab-' + release + '.yaml'] = P.dump(app)
    files['ansible/roles/monitoring/tasks/main.json'] = P.dump(tasks)


def credentials(repo, state, values):
    from . import provision as P
    if not state.get('observability'): return
    values.setdefault('grafana-admin-password', secrets.token_urlsafe(32))
    # Keep the stable credential encrypted before deploying even if Vault is not running yet.
    P.encrypt(repo, state['age_recipient'], values)
    if state['observability']['mode'] == 'host':
        P.run(P.ssh_args(state['target']) + ["sudo -n sh -c 'install -d -m 0755 /opt/bromigos-monitoring; umask 077; cat > /opt/bromigos-monitoring/grafana-password; chmod 0400 /opt/bromigos-monitoring/grafana-password'"], values['grafana-admin-password'])
        P.run(P.ssh_args(state['target']) + ['sudo -n chown 472:472 /opt/bromigos-monitoring/grafana-password'])


def cluster_secret(state, values, repo):
    from . import provision as P
    if not state.get('observability') or state['observability']['mode'] != 'cluster': return
    ns = {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': 'monitoring', 'annotations': {'bromigos.org/owner': 'lab-provision'}}}
    raw = P.kubectl(state['target'], ['get', 'namespace', 'monitoring', '--ignore-not-found', '-o', 'json'])
    if raw.strip() and json.loads(raw)['metadata'].get('annotations', {}).get('bromigos.org/owner') != 'lab-provision':
        raise P.ProvisionError('Monitoring namespace belongs to another installer')
    if raw.strip():
        existing = P.kubectl(state['target'], ['get', 'secret', 'lab-grafana-admin', '-n', 'monitoring', '--ignore-not-found', '-o', 'json'])
        if existing.strip():
            import base64
            values['grafana-admin-password'] = base64.b64decode(json.loads(existing)['data']['password']).decode()
            P.encrypt(repo, state['age_recipient'], values)
    P.kubectl(state['target'], ['apply', '-f', '-'], P.dump(ns))
    P.kubectl(state['target'], ['apply', '-f', '-'], P.dump({'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'lab-grafana-admin', 'namespace': 'monitoring'}, 'stringData': {'user': 'admin', 'password': values['grafana-admin-password']}}))


@contextlib.contextmanager
def endpoint(state, service):
    from . import provision as P
    if state['observability']['mode'] == 'cluster':
        with P.forward(state['target'], 'monitoring', CLUSTER_NAMES[service], PORTS[service], probe_path='/-/ready' if service in ('prometheus', 'alertmanager') else '/api/health' if service == 'grafana' else '/ready', ready_key=None) as address:
            yield address
        return
    port = 3001 if service == 'grafana' else PORTS[service]
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); local = sock.getsockname()[1]
    target = state['target']
    argv = P.ssh_args(target)[:-1] + ['-N', '-L', f'{local}:127.0.0.1:{port}', target['ssh']]
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            if proc.poll() is not None: raise P.ProvisionError('Monitoring tunnel failed')
            try:
                with socket.create_connection(('127.0.0.1', local), timeout=1): break
            except OSError: time.sleep(.1)
        else: raise P.ProvisionError('Monitoring tunnel did not start')
        yield 'http://127.0.0.1:' + str(local)
    finally:
        proc.terminate()
        try: proc.wait(5)
        except subprocess.TimeoutExpired: proc.kill(); proc.wait()


def get(state, service, path):
    from . import provision as P
    try:
        with endpoint(state, service) as url:
            with urllib.request.urlopen(url + path, timeout=20) as response: return json.load(response)
    except (OSError, ValueError):
        raise P.ProvisionError(service + ' did not answer its read-only check') from None


def verify(state):
    from . import provision as P
    if not state.get('observability'): return
    targets = get(state, 'prometheus', '/api/v1/targets')['data']['activeTargets']
    if not targets or any(t['health'] != 'up' for t in targets):
        raise P.ProvisionError('Some Prometheus targets are not up (' + str(sum(t['health'] != 'up' for t in targets)) + ' down)')
    if state['observability']['mode'] == 'cluster' and state['target']['kind'] == 'ssh' and 'netdata' in state['selected']:
        query = urllib.parse.urlencode({'query': 'up{job="netdata"}'})
        collected = get(state, 'prometheus', '/api/v1/query?' + query)['data']['result']
        if not collected or any(float(row['value'][1]) != 1 for row in collected):
            raise P.ProvisionError('Host Netdata metrics have not reached Prometheus')
    probes = get(state, 'prometheus', '/api/v1/query?query=probe_success')['data']['result']
    if any(float(row['value'][1]) != 1 for row in probes):
        raise P.ProvisionError('Some provisioned service health probes are failing')
    if get(state, 'grafana', '/api/health').get('database') != 'ok': raise P.ProvisionError('Grafana database is not healthy')
    get(state, 'alertmanager', '/api/v2/status')
    try:
        with endpoint(state, 'loki') as url:
            with urllib.request.urlopen(url + '/ready', timeout=20) as response:
                if response.status != 200: raise P.ProvisionError('Loki is not ready')
    except OSError:
        raise P.ProvisionError('Loki is not ready') from None
