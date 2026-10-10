"""Agent plans and credential boundaries use only made-up services and tokens."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from bromigos_homelab import agentprovision as A, provision as P, services as S

os.environ['BROMIGOS_LAB_PROFILES'] = str(Path(__file__).parents[1] / 'share/lab/profiles.toml')
TARGET = {'kind': 'ssh', 'ssh': 'test@lab.example.org', 'port': 22}
FACTS = {'cpu': 8, 'ram_gib': 32, 'disk_gib': 100, 'distribution': 'debian', 'architecture': 'x86_64'}
OPTIONS = {'endpoint': 'https://models.example.org/v1', 'model': 'example-model', 'catalog_model': 'external', 'profile': 'assistant', 'tools': 'memory', 'gateways': ['telegram', 'discord'], 'telegram_users': ['123456'], 'discord_users': ['789012']}

class AgentPlans(unittest.TestCase):
    def test_catalog_and_resolver(self):
        cat = S.load()
        self.assertEqual([], S.validate(cat))
        for agent in A.AGENTS:
            self.assertEqual(['agent'], cat['service'][agent]['provides'])
            resolved = S.resolve(cat, [agent, 'llm-endpoint'])
            self.assertEqual([], resolved['unmet'])
            self.assertNotIn('ollama', resolved['services'])
            self.assertNotIn('litellm', resolved['services'])
            self.assertIn('litellm', S.resolve(cat, [agent])['services'])
            self.assertIn('ollama', S.resolve(cat, [agent])['services'])
        self.assertTrue(S.resolve(cat, ['ollama', 'vllm'])['conflicts'])

    def test_goldens(self):
        for name, picked, target, opts in [
            ('agents-host', ['hermes', 'openclaw'], TARGET, OPTIONS),
            ('agents-cluster', ['hermes', 'openclaw'], {'kind': 'cluster', 'kubeconfig': '/tmp/example-kubeconfig', 'context': 'example'}, OPTIONS),
            ('nemoclaw', ['nemoclaw'], TARGET, dict(OPTIONS, gateways=[]))]:
            with self.subTest(name=name):
                files, _ = P.plan_files(target, picked, FACTS, age_recipient='age1example', agents=opts)
                self.assertEqual(files, json.loads((Path(__file__).parent / 'golden' / (name + '.json')).read_text()))
                self.assertNotIn('stringData', ''.join(files.values()))
                self.assertNotIn('test-secret-value', ''.join(files.values()))
                self.assertNotIn('hostPath', ''.join(files.values()))

    def test_messaging_tool_restrictions(self):
        hermes = A.configuration('hermes', OPTIONS)
        for surface in ('telegram', 'discord', 'api_server', 'cron'):
            self.assertEqual(list(A.SAFE_HERMES), hermes['platform_toolsets'][surface])
        self.assertIn('terminal', hermes['agent']['disabled_toolsets'])
        self.assertIn('file', hermes['agent']['disabled_toolsets'])
        claw = A.configuration('openclaw', OPTIONS)
        self.assertIn('group:runtime', claw['tools']['deny'])
        self.assertIn('group:fs', claw['tools']['deny'])
        for channel in ('telegram', 'discord'):
            self.assertEqual('allowlist', claw['channels'][channel]['dmPolicy'])
            self.assertEqual('disabled', claw['channels'][channel]['groupPolicy'])
        self.assertFalse(claw['gateway']['controlUi']['enabled'])
        self.assertFalse(claw['commands']['bash'])
        self.assertFalse(claw['commands']['config'])

    def test_reject_invalid_configuration(self):
        for changes in ({'endpoint': 'https://token@models.example.org/v1'}, {'endpoint': 'https://models.example.org/v1?key=test-secret-value'}, {'endpoint': 'https://models.example.org'}, {'tools': 'shell'}, {'telegram_users': []}, {'profile': '../../escape'}, {'gateways': ['unknown']}, {'catalog_model': 'not-in-catalog'}):
            with self.subTest(changes=changes), self.assertRaises(P.ProvisionError):
                A.validate(dict(OPTIONS, **changes), ['hermes'], TARGET)
        with self.assertRaises(P.ProvisionError):
            A.validate(OPTIONS, ['nemoclaw'], TARGET)
        with self.assertRaises(P.ProvisionError):
            A.validate(dict(OPTIONS, gateways=[]), ['nemoclaw'], {'kind': 'cluster'})
        with self.assertRaises(P.ProvisionError):
            P.plan_files(TARGET, ['hermes'], FACTS, agents=OPTIONS)

    def test_hidden_prompts_and_existing_credentials(self):
        secret = 'test-secret-value'
        opts = dict(OPTIONS)
        with mock.patch('getpass.getpass', return_value=secret) as prompt, mock.patch('builtins.input', side_effect=AssertionError('Unexpected visible prompt')), contextlib.redirect_stdout(io.StringIO()) as output:
            _, values = A.configure(['hermes'], opts)
        self.assertEqual(secret, values['hermes-env']['LLM_API_KEY'])
        self.assertNotIn(secret, output.getvalue())
        with mock.patch('getpass.getpass', side_effect=AssertionError('Unexpected repeated prompt')), mock.patch('builtins.input', side_effect=AssertionError('Unexpected visible prompt')):
            _, repeated = A.configure(['hermes'], opts, values)
        self.assertEqual(values, repeated)

    def test_runtime_secrets_only_in_stdin(self):
        state = {'selected': ['hermes'], 'target': TARGET, 'agents': OPTIONS}
        values = {'hermes-env': {'LLM_API_KEY': 'test-secret-value', 'AGENT_API_KEY': 'test-api-key', 'TELEGRAM_BOT_TOKEN': 'fake-bot', 'DISCORD_BOT_TOKEN': 'fake-discord'}}
        with mock.patch.object(P, 'run') as run:
            A.runtime_secrets(state, values)
        argv, data = run.call_args.args
        self.assertNotIn('test-secret-value', repr(argv))
        self.assertIn('test-secret-value', data)
        self.assertIn('umask 077', argv[-1])

    def test_metadata_projection_never_exposes_payload(self):
        state = {'selected': ['hermes'], 'target': TARGET, 'agents': OPTIONS}
        raw = {'status': 'running', 'model': 'example-model', 'gateways': 'api_server: connected', 'activity': '0 active', 'token': 'test-secret-value', 'messages': ['private text']}
        with mock.patch.object(P, 'run', return_value=json.dumps(raw)) as run:
            row = A.metadata(state, 'hermes')
        self.assertNotIn('test-secret-value', json.dumps(row))
        self.assertNotIn('private text', json.dumps(row))
        self.assertNotIn('logs', run.call_args.args[0][-1])

    def test_unrelated_runtime_is_not_overwritten(self):
        state = {'selected': ['hermes'], 'target': {'kind': 'cluster', 'kubeconfig': 'example', 'context': 'example'}, 'agents': OPTIONS}
        with mock.patch.object(P, 'kubectl', return_value=json.dumps({'metadata': {'name': 'lab-agents'}})) as kube, self.assertRaises(P.ProvisionError):
            A.runtime_secrets(state, {})
        self.assertEqual(1, kube.call_count)

    def test_cluster_runtime_and_keep_annotations(self):
        target = {'kind': 'cluster', 'kubeconfig': '/tmp/example-kubeconfig', 'context': 'example'}
        values = {'hermes-env': {'LLM_API_KEY': 'test-secret-value', 'AGENT_API_KEY': 'test-api-key'}}
        state = {'selected': ['hermes'], 'target': target, 'agents': dict(OPTIONS, gateways=[])}
        with mock.patch.object(P, 'kubectl', return_value='') as kube:
            A.runtime_secrets(state, values)
        self.assertIn('test-secret-value', kube.call_args.args[2])
        self.assertNotIn('test-secret-value', repr(kube.call_args.args[:2]))
        files, _ = P.plan_files(target, ['hermes'], FACTS, agents=state['agents'], age_recipient='age1example')
        docs = [json.loads(doc) for doc in files['helm/agents/templates/agents.yaml'].split('---\n')]
        self.assertTrue(all(d['metadata']['annotations']['helm.sh/resource-policy'] == 'keep' for d in docs))
        self.assertFalse(json.loads(files['ansible/playbooks/provision.json'])[0]['become'])

if __name__ == '__main__':
    unittest.main()
