"""Agent plans and credential boundaries use only made-up services and tokens."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from bromigos_homelab import agentprovision as A, connectors as C, provision as P, services as S

os.environ['BROMIGOS_LAB_PROFILES'] = str(Path(__file__).parents[1] / 'share/lab/profiles.toml')
TARGET = {'kind': 'ssh', 'ssh': 'test@lab.example.org', 'port': 22}
FACTS = {'cpu': 8, 'ram_gib': 32, 'disk_gib': 100, 'distribution': 'debian', 'architecture': 'x86_64'}
CLUSTER = {'kind': 'cluster', 'kubeconfig': '/tmp/example-kubeconfig', 'context': 'example'}
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
            ('agents-cluster', ['hermes', 'openclaw'], CLUSTER, OPTIONS),
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


# A made-up catalogue: one row for each thing a choice of connectors can meet.
CATALOGUE = '''
format = 1
checked = "2026-11-17"
connector_categories = ["Made up"]
platform_categories = ["Made up"]

[[connector]]
id = "docs"
name = "Example Docs"
category = "Made up"
auth = "none"
url = "https://docs.example.org/mcp"
official = true
homepage = "https://example.org"
summary = "Reads the docs."
answered = true
answer = "405"

[[connector]]
id = "web-search"
name = "Example Search"
category = "Made up"
auth = "key"
url = "https://search.example.org/mcp"
official = true
homepage = "https://example.org"
summary = "Searches."
answered = true
answer = "401"

[[connector]]
id = "bridge"
name = "Example Bridge"
category = "Made up"
auth = "key"
url = "https://bridge.example.org/mcp"
official = false
homepage = "https://example.org"
key_header = "x-example-key"
summary = "Bridges apps."
acts = "It can send email from the accounts you connect to it."
answered = true
answer = "401"

[[connector]]
id = "notes"
name = "Example Notes"
category = "Made up"
auth = "sign-in"
url = "https://notes.example.org/mcp"
official = true
homepage = "https://example.org"
summary = "Keeps notes."
answered = true
answer = "401"

[[connector]]
id = "mail"
name = "Example Mail"
category = "Made up"
auth = "key"
url = "https://mail.example.org/"
official = true
homepage = "https://example.org"
summary = "Reads mail."
listed_only = "It needs mail tools of our own. They aren't built."
answered = false
answer = "404"

[[connector]]
id = "quiet"
name = "Example Quiet"
category = "Made up"
auth = "none"
url = "https://quiet.example.org/mcp"
official = true
homepage = "https://example.org"
summary = "Says little."
answered = false
answer = "timed out"

[[platform]]
id = "shop"
name = "Example Shop"
category = "Made up"
env = "SHOP_API_KEY"
docs = "https://example.org/docs"
api_base = "https://api.example.org/v1"
summary = "Sells things."
'''
CONNECTED = dict(OPTIONS, connectors=['docs', 'web-search'])
KEY = 'fake-connector-key-0000'
NO_CATALOGUE = {'BROMIGOS_LAB_CONNECTORS': '/nonexistent/connectors.toml'}


class AgentConnectors(unittest.TestCase):
    """An agent's connectors: what's refused, what's generated, and where a key goes."""
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        path = Path(cls.tmp.name) / 'connectors.toml'
        path.write_text(CATALOGUE)
        cls.patches = [mock.patch.dict(os.environ, {'BROMIGOS_LAB_CONNECTORS': str(path)}), mock.patch.object(C, 'SHARE', '/nonexistent')]
        for patch in cls.patches:
            patch.start()

    @classmethod
    def tearDownClass(cls):
        for patch in cls.patches:
            patch.stop()
        cls.tmp.cleanup()

    def refused(self, picked=('hermes',), **changes):
        with self.assertRaises(P.ProvisionError) as error:
            A.validate(dict(OPTIONS, **changes), list(picked), TARGET)
        return str(error.exception)

    def golden(self, name):
        return json.loads((Path(__file__).parent / 'golden' / (name + '.json')).read_text())

    def test_goldens(self):
        self.assertEqual([], C.validate())
        for name, target, moved in (('agents-connectors-host', TARGET, {'plan.json', 'agents/compose.yaml', 'agents/hermes/config.yaml', 'agents/openclaw/openclaw.json'}),
                                    ('agents-connectors-cluster', CLUSTER, {'plan.json', 'agents/hermes/config.yaml', 'agents/openclaw/openclaw.json', 'helm/agents/templates/agents.yaml'})):
            with self.subTest(name=name):
                files, _ = P.plan_files(target, ['hermes', 'openclaw'], FACTS, age_recipient='age1example', agents=CONNECTED)
                self.assertEqual(files, self.golden(name))
                text = ''.join(files.values())
                for word in ('stringData', 'hostPath', 'NetworkPolicy', KEY):
                    self.assertNotIn(word, text)
                self.assertEqual(['docs', 'web-search'], json.loads(files['plan.json'])['agents']['connectors'])
                # Next to the plan without connectors, only the plan, the agents' own settings and their hash differ.
                plain = self.golden(name.replace('-connectors', ''))
                self.assertEqual(set(files), set(plain))
                self.assertEqual(moved, {k for k in files if files[k] != plain[k]})

    def test_servers_in_each_agents_own_format(self):
        quiet = {'sampling': {'enabled': False}, 'elicitation': {'enabled': False}, 'trust': 'untrusted'}
        self.assertEqual(A.configuration('hermes', CONNECTED)['mcp_servers'], {
            'connector_docs': {'url': 'https://docs.example.org/mcp', **quiet},
            'connector_web_search': {'url': 'https://search.example.org/mcp', 'headers': {'Authorization': 'Bearer ${CONNECTOR_WEB_SEARCH_KEY}'}, **quiet}})
        self.assertEqual(A.configuration('openclaw', CONNECTED)['mcp'], {'servers': {
            'connector_docs': {'url': 'https://docs.example.org/mcp', 'transport': 'streamable-http'},
            'connector_web_search': {'url': 'https://search.example.org/mcp', 'transport': 'streamable-http', 'headers': {'Authorization': 'Bearer ${CONNECTOR_WEB_SEARCH_KEY}'}}}})
        bridged = dict(OPTIONS, connectors=['bridge'], allow_acting=['bridge'])
        self.assertEqual({'x-example-key': '${CONNECTOR_BRIDGE_KEY}'}, A.configuration('hermes', bridged)['mcp_servers']['connector_bridge']['headers'])
        self.assertEqual({'x-example-key': '${CONNECTOR_BRIDGE_KEY}'}, A.configuration('openclaw', bridged)['mcp']['servers']['connector_bridge']['headers'])
        for agent, key in (('hermes', 'mcp_servers'), ('openclaw', 'mcp')):
            self.assertNotIn(key, A.configuration(agent, OPTIONS))
            self.assertNotIn(key, A.configuration(agent, dict(OPTIONS, connectors=[])))

    def test_write_calls_ask_first_unless_a_connector_is_trusted(self):
        servers = A.configuration('hermes', dict(OPTIONS, connectors=['docs', 'web-search', 'bridge'], allow_acting=['bridge']))['mcp_servers']
        self.assertEqual({'untrusted'}, {server['trust'] for server in servers.values()})
        trusted = dict(OPTIONS, connectors=['docs', 'web-search'], trust_connectors=['Web-Search'])
        servers = A.configuration('hermes', trusted)['mcp_servers']
        self.assertEqual(('untrusted', 'full'), (servers['connector_docs']['trust'], servers['connector_web_search']['trust']))
        # OpenClaw has no such setting: its servers are the same either way.
        self.assertEqual(A.configuration('openclaw', CONNECTED)['mcp'], A.configuration('openclaw', trusted)['mcp'])
        self.assertIn("--trust-connector names bridge, which isn't among the connectors chosen", self.refused(connectors=['docs'], trust_connectors=['bridge']))
        # One that acts is trusted only when it's allowed to act, by name.
        self.assertIn('add --allow-acting bridge', self.refused(connectors=['bridge'], trust_connectors=['bridge']))
        both = dict(OPTIONS, connectors=['bridge'], allow_acting=['bridge'], trust_connectors=['bridge'])
        A.validate(both, ['hermes'], TARGET)
        self.assertEqual('full', A.configuration('hermes', both)['mcp_servers']['connector_bridge']['trust'])
        self.assertEqual('untrusted', A.configuration('hermes', dict(both, trust_connectors=[]))['mcp_servers']['connector_bridge']['trust'])
        _, resolved = P.plan_files(TARGET, ['hermes'], FACTS, age_recipient='age1example', agents=trusted)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            P.summary(S.load(), resolved, FACTS, '/tmp/example-repo', trusted)
        self.assertIn('(docs) at https://docs.example.org/mcp; no key; Hermes asks before its write calls\n', out.getvalue())
        self.assertIn("its key comes from the agent's environment; trusted: Hermes runs its write calls without asking\n", out.getvalue())

    def test_every_existing_restriction_stays(self):
        plain, hermes = A.configuration('hermes', OPTIONS), A.configuration('hermes', CONNECTED)
        self.assertEqual(list(A.DENIED_HERMES), hermes['agent']['disabled_toolsets'])
        for surface in ('telegram', 'discord', 'api_server', 'cron'):
            self.assertEqual(list(A.SAFE_HERMES) + ['connector_docs', 'connector_web_search'], hermes['platform_toolsets'][surface])
        self.assertEqual(['connector_docs'], A.configuration('hermes', dict(OPTIONS, tools='none', connectors=['docs']))['platform_toolsets']['api_server'])
        # Nothing else in either agent's settings moves.
        self.assertEqual({k: v for k, v in plain.items() if k != 'platform_toolsets'}, {k: v for k, v in hermes.items() if k not in ('mcp_servers', 'platform_toolsets')})
        plain, claw = A.configuration('openclaw', OPTIONS), A.configuration('openclaw', CONNECTED)
        self.assertEqual(plain['tools']['deny'], claw['tools']['deny'])
        self.assertEqual(plain['tools']['allow'] + ['connector_docs__*', 'connector_web_search__*'], claw['tools']['allow'])
        self.assertEqual({k: v for k, v in plain.items() if k != 'tools'}, {k: v for k, v in claw.items() if k not in ('mcp', 'tools')})

    def test_each_refusal_says_why(self):
        self.assertIn("No connector has the id 'nothing'", self.refused(connectors=['nothing']))
        self.assertIn("Example Shop (shop) can't be given to an agent: it's a key platform, not a connector, and key platforms come in a later change.", self.refused(connectors=['shop']))
        self.assertIn('it needs a sign-in in a browser, and sign-in connectors come in a later change', self.refused(connectors=['notes']))
        self.assertIn("it's listed only. It needs mail tools of our own", self.refused(connectors=['mail']))
        self.assertIn("Example Quiet (quiet) didn't answer when its address was checked on 2026-11-17 (timed out). To choose it anyway, add --allow-unanswered quiet.", self.refused(connectors=['quiet']))
        self.assertIn('Example Bridge (bridge) can act for you. It can send email from the accounts you connect to it. To give it to an agent anyway, add --allow-acting bridge.', self.refused(connectors=['docs', 'bridge']))
        self.assertIn('at most 8 connectors, and 9 were chosen', self.refused(connectors=['docs'] + ['made-up-' + str(n) for n in range(8)]))
        self.assertIn("--allow-acting names bridge, which isn't among the connectors chosen", self.refused(connectors=['docs'], allow_acting=['bridge']))
        self.assertIn('Connectors are a list of ids', self.refused(connectors='docs'))
        self.assertIn('NemoClaw is given no connectors', self.refused(picked=['hermes', 'nemoclaw'], connectors=['docs'], gateways=[]))
        with self.assertRaises(P.ProvisionError):
            P.plan_files(TARGET, ['hermes'], FACTS, age_recipient='age1example', agents=dict(OPTIONS, connectors=['notes']))

    def test_naming_one_a_second_time_allows_it(self):
        A.validate(dict(OPTIONS, connectors=['docs', 'bridge'], allow_acting=['bridge']), ['hermes'], TARGET)
        A.validate(dict(OPTIONS, connectors=['quiet'], allow_unanswered=['quiet']), ['openclaw'], TARGET)
        A.validate(dict(OPTIONS, connectors=[], gateways=[]), ['nemoclaw'], TARGET)             # none chosen: nothing to refuse

    def test_a_catalogue_that_cannot_be_read_stops_the_plan(self):
        with mock.patch.dict(os.environ, NO_CATALOGUE), mock.patch.object(C, 'HERE', '/nonexistent/a/b'):
            self.assertIn('no connectors.toml', self.refused(connectors=['docs']))
            A.validate(OPTIONS, ['hermes'], TARGET)                # no connectors: the catalogue is never read

    def test_the_key_is_asked_hidden_and_reused(self):
        prompts = []

        def hidden(prompt):
            prompts.append(prompt)
            return KEY if 'connector' in prompt else 'test-secret-value'
        no_question = mock.patch('builtins.input', side_effect=AssertionError('Unexpected visible prompt'))
        with mock.patch('getpass.getpass', side_effect=hidden), no_question, \
                contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            options, values = A.configure(['hermes', 'openclaw'], dict(CONNECTED))
        self.assertEqual(['Example Search API key, for the web-search connector: '], [p for p in prompts if 'connector' in p])    # one key serves both agents
        self.assertNotIn(KEY, out.getvalue() + err.getvalue() + repr(prompts) + json.dumps(options))
        for agent in ('hermes', 'openclaw'):
            self.assertEqual(KEY, values[agent + '-env']['CONNECTOR_WEB_SEARCH_KEY'])
            self.assertNotIn('CONNECTOR_DOCS_KEY', values[agent + '-env'])
        with mock.patch('getpass.getpass', side_effect=AssertionError('Unexpected repeated prompt')), no_question:
            # Planning again reuses what was encrypted: nothing is asked.
            _, repeated = A.configure(['hermes', 'openclaw'], dict(CONNECTED), values)
            self.assertEqual(values, repeated)
            # An agent added later takes the key the first one has.
            later = {'hermes-env': values['hermes-env'], 'openclaw-env': {k: v for k, v in values['openclaw-env'].items() if k != 'CONNECTOR_WEB_SEARCH_KEY'}}
            _, added = A.configure(['hermes', 'openclaw'], dict(CONNECTED), later)
            self.assertEqual(KEY, added['openclaw-env']['CONNECTOR_WEB_SEARCH_KEY'])
            # A connector that's no longer chosen loses its key, and nothing else.
            _, dropped = A.configure(['hermes', 'openclaw'], dict(OPTIONS, connectors=['docs']), values)
        self.assertNotIn(KEY, json.dumps(dropped))
        self.assertEqual({k: v for k, v in values['hermes-env'].items() if k != 'CONNECTOR_WEB_SEARCH_KEY'}, dropped['hermes-env'])
        with mock.patch('getpass.getpass', return_value=''), no_question, self.assertRaises(P.ProvisionError) as error:
            A.configure(['hermes'], dict(CONNECTED), {'hermes-env': {'LLM_API_KEY': 'test-secret-value', 'TELEGRAM_BOT_TOKEN': 'fake-bot', 'DISCORD_BOT_TOKEN': 'fake-discord'}})
        self.assertEqual('The web-search connector needs its key', str(error.exception))

    def test_a_refused_choice_asks_for_no_key(self):
        with mock.patch('getpass.getpass', side_effect=AssertionError('Asked for a key')), self.assertRaises(P.ProvisionError):
            A.configure(['hermes'], dict(OPTIONS, connectors=['web-search', 'bridge']))

    def test_the_connectors_question_goes_with_the_tools_question(self):
        asked = []
        options = {k: v for k, v in OPTIONS.items() if k != 'tools'}

        def answers(*typed):
            typed = iter(typed)

            def visible(prompt):
                asked.append(prompt)
                return next(typed)
            return mock.patch('builtins.input', side_effect=visible)
        with answers('memory', 'docs, web-search'), mock.patch('getpass.getpass', return_value=KEY), contextlib.redirect_stdout(io.StringIO()) as out:
            chosen, _ = A.configure(['hermes'], dict(options))
        self.assertEqual(['docs', 'web-search'], chosen['connectors'])
        self.assertIn('bromigos lab connectors lists them [none]', asked[1])
        self.assertNotIn(KEY, out.getvalue() + repr(asked))
        for typed in ('', 'none'):
            with answers('memory', typed), mock.patch('getpass.getpass', return_value='test-secret-value'):
                self.assertEqual([], A.configure(['hermes'], dict(options))[0]['connectors'])
        # A plan that answered the tools question before connectors existed is asked nothing, and keeps none.
        with mock.patch('builtins.input', side_effect=AssertionError('Unexpected visible prompt')), mock.patch('getpass.getpass', return_value='test-secret-value'):
            self.assertEqual([], A.configure(['hermes'], dict(OPTIONS))[0]['connectors'])
        with answers('memory', 'bridge'), mock.patch('getpass.getpass', side_effect=AssertionError('Asked for a key')), self.assertRaises(P.ProvisionError) as error:
            A.configure(['hermes'], dict(options))
        self.assertIn('add --allow-acting bridge', str(error.exception))

    def test_command_line_options(self):
        import argparse

        def args(**given):
            return argparse.Namespace(**{'connectors': None, 'allow_acting': [], 'allow_unanswered': [], 'trust_connector': [], **given})
        fresh = {'endpoint': '', 'model': ''}
        self.assertEqual(fresh, P.connector_options(args(), fresh))
        self.assertEqual(dict(fresh, connectors=['docs']), P.connector_options(args(connectors=['docs']), fresh))
        self.assertEqual(dict(fresh, connectors=[]), P.connector_options(args(connectors=[]), fresh))
        self.assertEqual(dict(fresh, connectors=['bridge', 'quiet'], allow_acting=['bridge'], allow_unanswered=['quiet']),
                         P.connector_options(args(connectors=['bridge', 'quiet'], allow_acting=['bridge'], allow_unanswered=['quiet']), fresh))
        saved = dict(OPTIONS, connectors=['bridge'], allow_acting=['bridge'])
        self.assertEqual(saved, P.connector_options(args(), saved))                                   # a saved plan keeps its choice
        self.assertEqual(dict(OPTIONS, connectors=['docs']), P.connector_options(args(connectors=['docs']), saved))
        self.assertEqual(dict(fresh, connectors=['docs'], trust_connectors=['docs']), P.connector_options(args(connectors=['docs'], trust_connector=['docs']), fresh))
        for alone in ({'allow_acting': ['bridge']}, {'allow_unanswered': ['quiet']}, {'trust_connector': ['docs']}):
            with self.assertRaises(P.ProvisionError):
                P.connector_options(args(**alone), fresh)

    def test_the_key_reaches_the_agent_only_through_stdin(self):
        env = {'LLM_API_KEY': 'test-secret-value', 'AGENT_API_KEY': 'test-api-key', 'TELEGRAM_BOT_TOKEN': 'fake-bot', 'DISCORD_BOT_TOKEN': 'fake-discord'}
        values = {agent + '-env': dict(env, CONNECTOR_WEB_SEARCH_KEY=KEY) for agent in ('hermes', 'openclaw')}
        state = {'selected': ['hermes', 'openclaw'], 'target': TARGET, 'agents': CONNECTED}
        with mock.patch.object(P, 'run') as run, contextlib.redirect_stdout(io.StringIO()) as out:
            A.runtime_secrets(state, values)
        sent = [call.args for call in run.call_args_list if len(call.args) > 1]
        self.assertEqual(2, len(sent))
        for argv, data in sent:
            self.assertIn('CONNECTOR_WEB_SEARCH_KEY=' + KEY + '\n', data)
            self.assertIn('umask 077', argv[-1])
        self.assertNotIn(KEY, repr([call.args[0] for call in run.call_args_list]) + out.getvalue())
        with mock.patch.object(P, 'kubectl', return_value='') as kube:
            A.runtime_secrets(dict(state, target=CLUSTER), values)
        secrets = [json.loads(call.args[2]) for call in kube.call_args_list if len(call.args) > 2 and '"Secret"' in call.args[2]]
        self.assertEqual([KEY, KEY], [doc['stringData']['CONNECTOR_WEB_SEARCH_KEY'] for doc in secrets])
        self.assertNotIn(KEY, repr([call.args[:2] for call in kube.call_args_list]))
        # sops takes it through stdin, as it does the agent's other credentials.
        with tempfile.TemporaryDirectory() as repo, mock.patch.object(P, 'run', return_value='{"sops": "ciphertext"}') as run:
            P.encrypt(repo, 'age1example', values)
            self.assertNotIn(KEY, repr(run.call_args.args[0]))
            self.assertIn(KEY, run.call_args.args[1])
            self.assertNotIn(KEY, (Path(repo) / 'secrets.enc.json').read_text())
        with mock.patch.object(P, 'run'), self.assertRaises(P.ProvisionError) as error:
            A.runtime_secrets(dict(state, selected=['hermes']), {'hermes-env': env})
        self.assertIn('The key for the web-search connector is missing', str(error.exception))

    def test_changed_settings_restart_the_agent(self):
        import hashlib

        def marks(target, options):
            files, _ = P.plan_files(target, ['hermes', 'openclaw'], FACTS, age_recipient='age1example', agents=options)
            if target is TARGET:
                services = json.loads(files['agents/compose.yaml'])['services']
                found = {agent: services[agent]['labels']['org.bromigos.lab.settings-sha256'] for agent in services}
            else:
                docs = [json.loads(doc) for doc in files['helm/agents/templates/agents.yaml'].split('---\n')]
                found = {d['metadata']['name']: d['spec']['template']['metadata']['annotations']['bromigos.org/settings-sha256'] for d in docs if d['kind'] == 'Deployment'}
            # The mark is the settings file's hash, and that file holds no credential.
            self.assertEqual(found, {'hermes': hashlib.sha256(files['agents/hermes/config.yaml'].encode()).hexdigest(),
                                     'openclaw': hashlib.sha256(files['agents/openclaw/openclaw.json'].encode()).hexdigest()})
            return found
        for target in (TARGET, CLUSTER):
            with self.subTest(target=target['kind']):
                with_two, with_one, plain = marks(target, CONNECTED), marks(target, dict(OPTIONS, connectors=['docs'])), marks(target, OPTIONS)
                self.assertEqual(with_two, marks(target, dict(CONNECTED)))              # the same plan: no restart
                for agent in ('hermes', 'openclaw'):
                    self.assertEqual(3, len({with_two[agent], with_one[agent], plain[agent]}))

    def test_a_dropped_connector_leaves_no_key_behind(self):
        env = {'LLM_API_KEY': 'test-secret-value', 'AGENT_API_KEY': 'test-api-key', 'TELEGRAM_BOT_TOKEN': 'fake-bot', 'DISCORD_BOT_TOKEN': 'fake-discord'}
        saved = {'hermes-env': dict(env, CONNECTOR_WEB_SEARCH_KEY=KEY)}
        without = dict(OPTIONS, connectors=['docs'])
        with mock.patch('getpass.getpass', side_effect=AssertionError('Unexpected prompt')):
            options, values = A.configure(['hermes'], dict(without), saved)
        self.assertEqual({'hermes-env': env}, values)                       # what sops encrypts next, and Vault stores
        for target in (TARGET, CLUSTER):
            files, _ = P.plan_files(target, ['hermes'], FACTS, age_recipient='age1example', agents=options)
            self.assertNotIn('CONNECTOR_WEB_SEARCH', ''.join(files.values()))
        state = {'selected': ['hermes'], 'target': TARGET, 'agents': options}
        # On a box the env file is written whole, so the old line goes with it.
        with mock.patch.object(P, 'run') as run:
            A.runtime_secrets(state, values)
        argv, data = run.call_args.args
        self.assertIn("cat > /opt/bromigos-agents/hermes.env", argv[-1])
        self.assertNotIn('>>', argv[-1])
        self.assertNotIn('CONNECTOR_', data)
        # On a cluster the Secret is replaced whole, never merged: an apply would leave the old key in its data.
        for found, verb in (('secret/hermes-env\n', 'replace'), ('', 'create')):
            with mock.patch.object(P, 'kubectl', side_effect=lambda target, args, data=None: found if 'secret' in args else '') as kube:
                A.runtime_secrets(dict(state, target=CLUSTER), values)
            calls = [call.args for call in kube.call_args_list]
            looked = [args for _, args, *_ in calls if 'secret' in args]
            self.assertEqual([['-n', 'lab-agents', 'get', 'secret', 'hermes-env', '--ignore-not-found', '-o', 'name']], looked)   # its name only
            sent = [(args, json.loads(data[0])) for _, args, *data in calls if data and '"Secret"' in data[0]]
            self.assertEqual([[verb, '-f', '-']], [args for args, _ in sent])
            self.assertEqual(A.environment('hermes', options, env), sent[0][1]['stringData'])
            self.assertNotIn('CONNECTOR_', json.dumps(sent[0][1]))
            self.assertEqual({'name': 'hermes-env', 'namespace': 'lab-agents'}, sent[0][1]['metadata'])

    def test_the_key_is_in_no_generated_file_and_no_output(self):
        for target in (TARGET, CLUSTER):
            files, resolved = P.plan_files(target, ['hermes', 'openclaw'], FACTS, age_recipient='age1example', agents=CONNECTED)
            with contextlib.redirect_stdout(io.StringIO()) as out:
                P.summary(S.load(), resolved, FACTS, '/tmp/example-repo', CONNECTED)
            text = ''.join(files.values()) + ''.join(files) + out.getvalue()
            self.assertNotIn(KEY, text)
            self.assertNotIn('fake-connector', text)
            self.assertIn('${CONNECTOR_WEB_SEARCH_KEY}', text)
            self.assertIn('  Connector: Example Docs (docs) at https://docs.example.org/mcp; no key; Hermes asks before its write calls\n', out.getvalue())
            self.assertIn("  Connector: Example Search (web-search) at https://search.example.org/mcp; its key comes from the agent's environment; Hermes asks before its write calls\n", out.getvalue())
        with contextlib.redirect_stdout(io.StringIO()) as out:
            P.summary(S.load(), resolved, FACTS, '/tmp/example-repo', dict(OPTIONS, connectors=['bridge'], allow_acting=['bridge']))
        self.assertIn('    Allowed to act. It can send email from the accounts you connect to it.\n', out.getvalue())

    def test_the_card_lists_connectors_by_id_and_name_only(self):
        state = {'selected': ['hermes'], 'target': TARGET, 'agents': CONNECTED}
        raw = {'status': 'running', 'model': 'example-model', 'gateways': 'api_server: connected', 'activity': '0 active',
               'connectors': ['connector_web_search', 'connector_docs', 'connector_bridge', 'https://search.example.org/mcp', KEY, {'headers': KEY}]}
        with mock.patch.object(P, 'run', return_value=json.dumps(raw)) as run:
            row = A.metadata(state, 'hermes')
        self.assertEqual('docs (Example Docs), web-search (Example Search)', row['connectors'])
        self.assertNotIn(KEY, json.dumps(row))
        self.assertNotIn('example.org', json.dumps(row))
        self.assertIn('mcp_servers', run.call_args.args[0][-1])
        self.assertNotIn('headers', run.call_args.args[0][-1])
        with mock.patch.object(P, 'run', return_value=json.dumps(dict(raw, connectors=[]))):
            self.assertEqual('none', A.metadata(state, 'hermes')['connectors'])
        with mock.patch.object(P, 'run', return_value=json.dumps({'status': 'running'})):
            self.assertEqual('unknown', A.metadata(state, 'hermes')['connectors'])
        with mock.patch.object(P, 'run', return_value=json.dumps(raw)), mock.patch.dict(os.environ, NO_CATALOGUE), mock.patch.object(C, 'HERE', '/nonexistent/a/b'):
            self.assertEqual('docs, web-search', A.metadata(state, 'hermes')['connectors'])
        with mock.patch.object(P, 'kubectl', return_value=json.dumps(dict(raw, connectors=['connector_docs']))) as kube:
            self.assertEqual('docs (Example Docs)', A.metadata(dict(state, selected=['openclaw'], target=CLUSTER), 'openclaw')['connectors'])
        self.assertIn('servers', kube.call_args.args[1][-1])


class ShippedConnectors(unittest.TestCase):
    """The same checks against the catalogue bromigOS ships."""
    def setUp(self):
        patch = mock.patch.object(C, 'SHARE', '/nonexistent')
        patch.start()
        self.addCleanup(patch.stop)

    def test_what_the_shipped_catalogue_gives_and_refuses(self):
        A.validate(dict(OPTIONS, connectors=['context7', 'tavily']), ['hermes', 'openclaw'], TARGET)
        for rid, why in (('zapier', 'add --allow-acting zapier'), ('composio', 'add --allow-acting composio'), ('stripe', 'move money, within what its key allows. To give it to an agent anyway, add --allow-acting stripe'),
                         ('paypal', 'needs a sign-in'), ('square', 'needs a sign-in'), ('ramp', 'needs a sign-in'), ('adspirer', 'needs a sign-in'), ('markifact', 'needs a sign-in'),
                         ('lob', 'key platform'), ('bland', 'key platform'), ('vapi', 'key platform'), ('github', 'listed only'), ('replaid', 'needs a sign-in'),
                         ('unreal-engine', 'your own machine'), ('atlassian', 'no address of its own')):
            with self.subTest(connector=rid):
                with self.assertRaises(P.ProvisionError) as error:
                    A.validate(dict(OPTIONS, connectors=[rid]), ['hermes'], TARGET)
                self.assertIn(why, str(error.exception))
        composio = dict(OPTIONS, connectors=['composio'], allow_acting=['composio'])
        self.assertEqual({'x-consumer-api-key': '${CONNECTOR_COMPOSIO_KEY}'}, A.configuration('hermes', composio)['mcp_servers']['connector_composio']['headers'])


if __name__ == '__main__':
    unittest.main()
