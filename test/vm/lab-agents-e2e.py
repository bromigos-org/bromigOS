#!/usr/bin/env python3
"""Fresh Debian, real Hermes/OpenClaw images, stub inference, no external bots.

It gives both agents one connector from the catalogue, checks that each starts with it and offers
its tools, applies the same plan again, then takes the connector away. docs/lab-agents.md says how
to run it. The guest reaches the connector's own server, and no other."""
import contextlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import socket
import subprocess
import sys
import time
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'homelab/lib'), str(ROOT / 'lib')]
os.environ['BROMIGOS_LAB_PROFILES'] = str(ROOT / 'homelab/share/lab/profiles.toml')
os.environ['BROMIGOS_LAB_CONNECTORS'] = str(ROOT / 'homelab/share/lab/connectors.toml')    # this checkout's, not an installed one
from bromigos_homelab import provision as P, agentprovision as A, services as S

STUB = '''import json,time
from http.server import BaseHTTPRequestHandler,HTTPServer
MARK='List the connector tools.'
def name(tool): return str((tool.get('function') or tool).get('name'))
TEXT='context7 library documentation'
def value(field):
 # A value that fits the field's own schema: one type, a list of types, or a choice of shapes ("a list, or nothing").
 shapes=[field]+list(field.get('anyOf') or [])+list(field.get('oneOf') or [])
 for shape in shapes:
  kind=shape.get('type')
  kinds=set(kind if isinstance(kind,list) else [kind])
  if 'array' in kinds: return [value(shape.get('items') or {'type':'string'})]
  if 'object' in kinds: return fill(shape)
  if kinds&{'integer','number'}: return 5
  if 'boolean' in kinds: return False
  if 'string' in kinds: return (shape.get('enum') or [TEXT])[0]
 return TEXT
def fill(schema):
 # The required fields, and any query field.
 return {key:value(field) for key,field in (schema.get('properties') or {}).items() if key in (schema.get('required') or []) or key.startswith('quer')}
def arguments(tool):
 # Whatever the agent's own tool_search asks for.
 return fill((tool.get('function') or tool).get('parameters') or {})
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args): pass
 def do_GET(self):
  self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(json.dumps({'data':[{'id':'test-model','object':'model','owned_by':'test'}]}).encode())
 def do_POST(self):
  q=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
  tools=q.get('tools') or []
  messages=q.get('messages') or []
  # What the agent offers the model, and what its tools answered: the test reads both files.
  open('/opt/lab-test-model-tools.jsonl','a').write(json.dumps(sorted(name(t) for t in tools))+'\\n')
  results=[m.get('content') for m in messages if m.get('role')=='tool']
  if results: open('/opt/lab-test-model-results.jsonl','a').write(json.dumps(results)+'\\n')
  # Asked to list the connector's tools, the stub calls the agent's own tool_search once, then answers.
  asked=any(MARK in json.dumps(m.get('content')) for m in messages if m.get('role')=='user')
  search=next((t for t in tools if name(t)=='tool_search'),None)
  call={'id':'call_search','type':'function','function':{'name':'tool_search','arguments':json.dumps(arguments(search))}} if asked and search and not results else None
  self.send_response(200); self.send_header('Content-Type','text/event-stream' if q.get('stream') else 'application/json'); self.end_headers()
  base={'id':'test-completion','object':'chat.completion','created':int(time.time()),'model':'test-model'}
  said={'role':'assistant','content':None,'tool_calls':[call]} if call else {'role':'assistant','content':'Agent test passed.'}
  done='tool_calls' if call else 'stop'
  if q.get('stream'):
   if call: said=dict(said,tool_calls=[dict(call,index=0)])
   for delta,finish in [(said,None),({},done)]:
    d={**base,'object':'chat.completion.chunk','choices':[{'index':0,'delta':delta,'finish_reason':finish}]}
    self.wfile.write(('data: '+json.dumps(d)+'\\n\\n').encode()); self.wfile.flush()
   self.wfile.write(b'data: [DONE]\\n\\n')
  else:
   self.wfile.write(json.dumps({**base,'choices':[{'index':0,'message':said,'finish_reason':done}],'usage':{'prompt_tokens':10,'completion_tokens':4,'total_tokens':14}}).encode())
HTTPServer(('0.0.0.0',8000),Handler).serve_forever()
'''


# The connector this test gives the agents. Context7 serves public library documentation: it
# needs no sign-in and no key, its maker runs it, and the catalogue's check found it answering.
CONNECTOR = 'context7'
SERVER = A.server_name(CONNECTOR)
SEEN = '/opt/lab-test-model-tools.jsonl'      # the stub endpoint writes each request's tool names here
RESULTS = '/opt/lab-test-model-results.jsonl'  # and what the agent's tools answered
DENIED = ('terminal', 'process', 'exec', 'bash', 'read', 'write', 'edit', 'apply_patch', 'read_file', 'write_file', 'patch', 'search_files', 'execute_code', 'browser')


def sized_for_plan(facts, picked):
    """The guest's real inventory with only its memory raised to what the plan asks for, and that figure.

    The service catalogue sizes each service for a real server. The four monitoring services every plan
    carries, two agents and the headroom come to about 15 GiB. test/vm/vm-keeper.py caps a test VM at
    8 GiB on purpose, and this test keeps to that cap. It is about installing and starting the agents,
    not about sizing, so apply is told the plan's own figure for memory and nothing else is changed.
    If the guest really is too small, a container dies and the checks below fail: nothing hides that."""
    cat = S.load()
    asked = sum(float(cat['service'][s].get('needs', {}).get('ram_gib', 0)) for s in P.selection(cat, picked)['services'])
    asked += cat.get('sizing', {}).get('ram_headroom_gib', 4)
    sized = dict(facts, ram_gib=max(facts['ram_gib'], asked))
    left = [w for w in P.selection(cat, picked, sized)['warnings'] if 'unknown' not in w]
    if left:
        raise SystemExit('The guest is too small in a way this test does not adjust: ' + '; '.join(left))
    return sized, asked


def main():
    original_home = Path.home()
    base = Path(os.environ.get('BROMIGOS_AGENT_TEST_DIR', original_home / '.cache/bromigos-agents-e2e'))
    if base.exists():
        raise SystemExit('Use a new BROMIGOS_AGENT_TEST_DIR')
    base.mkdir(parents=True)
    sandbox = base / 'home'
    sandbox.mkdir()
    observed = base / 'observed'
    observed.mkdir()
    for key in list(os.environ):
        if key.startswith('VAULT_') or key in ('KUBECONFIG', 'BROMIGOS_HOMELAB_CONFIG', 'SSH_AUTH_SOCK'):
            os.environ.pop(key, None)
    os.environ.update(HOME=str(sandbox), XDG_CONFIG_HOME=str(sandbox / '.config'), XDG_DATA_HOME=str(sandbox / '.local/share'), XDG_CACHE_HOME=str(sandbox / '.cache'))
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    # 8192 MiB is the most the keeper allows by default. sized_for_plan() says why that is enough here.
    env = dict(os.environ, BROMIGOS_VM_DIR=str(base / 'vm'), BROMIGOS_VM_PORT=str(port), BROMIGOS_VM_OWNER=str(os.getpid()), BROMIGOS_VM_MEM=os.environ.get('BROMIGOS_VM_MEM', '8192'),
               BROMIGOS_PROVISION_IMAGE=os.environ.get('BROMIGOS_PROVISION_IMAGE', str(original_home / '.cache/bromigos-provision-debian-final/vm/debian-12-genericcloud-amd64.qcow2')))
    if not Path(env['BROMIGOS_PROVISION_IMAGE']).exists() and not os.environ.get('BROMIGOS_PROVISION_IMAGE'):
        env.pop('BROMIGOS_PROVISION_IMAGE')
    harness = str(ROOT / 'test/vm/lab-vm.py')
    age_key = base / 'age.key'
    capture = io.StringIO()
    started = time.monotonic()
    target = None

    def guest(command):
        return P.run(P.ssh_args(target) + [command])

    def look(name, command):
        """What a command in the guest prints, kept in the test folder. It never fails the test."""
        try:
            text = guest('{ ' + command + '; } 2>&1 || true')
        except P.ProvisionError as error:
            text = 'not read: ' + str(error)
        (observed / name).write_text(text)
        return text

    def container(agent, full=False):
        return 'sudo -n docker ps -q ' + ('--no-trunc ' if full else '') + '--filter label=com.docker.compose.project=bromigos-agents --filter label=com.docker.compose.service=' + agent

    def containers():
        return {agent: guest(container(agent, True)).strip() for agent in ('hermes', 'openclaw')}

    def answer(agent, say='Say the test phrase.'):
        """A real turn from inside the container, with its own key; no key in argv. Returns the tool
        names the agent offered the model for it, as the stub endpoint recorded them."""
        guest('sudo -n truncate -s 0 ' + SEEN + ' ' + RESULTS)
        if agent == 'hermes':
            argv = ['python3', '-c', "import os,json,urllib.request; r=urllib.request.Request('http://127.0.0.1:8642/v1/chat/completions',data=json.dumps({'model':'test-model','messages':[{'role':'user','content':" + repr(say) + "}],'stream':False}).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+os.environ['API_SERVER_KEY']}); d=json.load(urllib.request.urlopen(r,timeout=120)); assert 'Agent test passed' in d['choices'][0]['message']['content']; print('answer verified')"]
        else:
            argv = ['node', '-e', "fetch('http://127.0.0.1:18789/v1/chat/completions',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+process.env.AGENT_API_KEY},body:JSON.stringify({model:'openclaw:assistant',messages:[{role:'user',content:" + repr(say) + "}],stream:false})}).then(async r=>{const d=await r.json();if(!r.ok||!JSON.stringify(d).includes('Agent test passed'))process.exit(1);console.log('answer verified')}).catch(()=>process.exit(1))"]
        assert guest('sudo -n docker exec $(' + container(agent) + ') ' + shlex.join(argv)).strip() == 'answer verified'
        return sorted({name for line in guest('sudo -n cat ' + SEEN).splitlines() if line.strip() for name in json.loads(line)})

    def listed(agent):
        """What the running agent's own tool search answers for the connector, as text ('': it has no
        tool search, or nothing came back). Both agents keep a server's tools behind tool_search,
        tool_describe and tool_call, so the model's tool list alone doesn't name them. The stub endpoint
        calls tool_search once, as a model would, and the agent's answer is read back. No tool of the
        connector's is called."""
        answer(agent, 'List the connector tools.')
        return guest('sudo -n cat ' + RESULTS)

    def apply(sized):
        with mock.patch('builtins.input', return_value='yes'), contextlib.redirect_stdout(capture):
            P.apply(repo, live_facts=sized)
        state = json.loads((repo / 'plan.json').read_text())
        A.verify(state)
        doctor = json.loads(P.run([str(ROOT / 'homelab/bin/bromigos-lab'), 'doctor', '--json']))
        (observed / 'doctor.json').write_text(json.dumps(doctor, indent=1))
        assert not doctor['summary'].get('fail') and not doctor['summary'].get('warn'), 'The doctor is not green: see observed/doctor.json'
        return state

    def lap(what):
        print(f'[{time.monotonic() - started:6.0f} s] {what}', flush=True)

    try:
        subprocess.run([sys.executable, harness, 'up'], env=env, check=True)
        target = {'kind': 'ssh', 'ssh': 'tester@127.0.0.1', 'port': port, 'identity': str(base / 'vm/id_ed25519')}
        known = base / 'known_hosts'
        known.write_text(subprocess.check_output(['ssh-keyscan', '-p', str(port), '127.0.0.1'], stderr=subprocess.DEVNULL, text=True))
        target['known_hosts'] = str(known)
        repo = base / 'lab'
        facts = P.inventory(target)
        picked = ['hermes', 'openclaw']
        sized, asked = sized_for_plan(facts, picked)
        lap(f"guest up: {facts['ram_gib']} GiB of memory, {facts['cpu']} CPUs; the plan asks for {asked:.1f} GiB, so apply is told that (see sized_for_plan)")
        recipient = subprocess.run(['age-keygen', '-o', str(age_key)], capture_output=True, text=True, check=True).stderr.split('Public key: ')[1].strip()
        os.environ['SOPS_AGE_KEY_FILE'] = str(age_key)
        os.environ['XDG_CONFIG_HOME'] = str(base / 'home/.config')
        os.environ['BROMIGOS_HOMELAB_CONFIG'] = str(base / 'home/.config/bromigos/homelab.toml')
        opts = {'endpoint': 'http://lab-model-host:8000/v1', 'model': 'test-model', 'profile': 'assistant', 'tools': 'none', 'gateways': [], 'connectors': [CONNECTOR]}
        files, _ = P.plan_files(target, picked, facts, age_recipient=recipient, agents=opts)
        P.generate(repo, files)
        values = {a + '-env': {'LLM_API_KEY': secrets.token_urlsafe(32), 'AGENT_API_KEY': secrets.token_urlsafe(32)} for a in picked}
        P.encrypt(repo, recipient, values)
        fixture = [P.task('Install isolated stub', 'ansible.builtin.copy', {'content': STUB, 'dest': '/opt/lab-test-model.py', 'mode': '0600'}),
                   P.task('Install stub unit', 'ansible.builtin.copy', {'content': '[Unit]\nDescription=Throwaway model stub\n[Service]\nExecStart=/usr/bin/python3 /opt/lab-test-model.py\n[Install]\nWantedBy=multi-user.target\n', 'dest': '/etc/systemd/system/lab-test-model.service'}),
                   P.task('Start isolated stub', 'ansible.builtin.systemd', {'name': 'lab-test-model', 'state': 'started', 'daemon_reload': True})]
        fixture_path = base / 'fixture.json'
        fixture_path.write_text(P.dump([{'hosts': 'all', 'become': True, 'gather_facts': False, 'tasks': fixture}]))
        P.run(['ansible-playbook', '-i', str(repo / 'ansible/inventory/hosts.json'), str(fixture_path)], env=dict(os.environ, ANSIBLE_NO_LOG='true'))
        state = apply(sized)
        lap('first apply done: both agents healthy, doctor green')
        tool_check = ['python3', '-c', "import os,json,urllib.request; r=urllib.request.Request('http://127.0.0.1:8642/v1/toolsets',headers={'Authorization':'Bearer '+os.environ['API_SERVER_KEY']}); d=json.load(urllib.request.urlopen(r,timeout=20)); assert not any(x['enabled'] and x['name'] in ('terminal','file','browser','code_execution') for x in d['data']); print('tool policy verified')"]
        assert guest('sudo -n docker exec $(' + container('hermes') + ') ' + shlex.join(tool_check)).strip() == 'tool policy verified'

        # The connector, as each agent has it. Everything seen is kept before anything is judged.
        offered, found, rows = {}, {}, {}
        for agent in picked:
            offered[agent] = answer(agent)
            for _ in range(6):                                   # an agent connects to its servers after it starts
                found[agent] = listed(agent)
                if SERVER in found[agent] or any(SERVER in name for name in offered[agent]):
                    break
                time.sleep(10)
            (observed / (agent + '-tool-search.txt')).write_text(found[agent])
            rows[agent] = A.metadata(state, agent)
            print('PASS: ' + agent + ' health, metadata and real agent response against isolated stub')
        look('hermes-mcp-list.txt', 'sudo -n timeout 90 docker exec $(' + container('hermes') + ') hermes -p default mcp list')
        look('hermes-mcp-test.txt', 'sudo -n timeout 90 docker exec $(' + container('hermes') + ') hermes -p default mcp test ' + SERVER)
        look('openclaw-mcp-list.txt', 'sudo -n timeout 90 docker exec $(' + container('openclaw') + ') node openclaw.mjs mcp list')
        look('openclaw-mcp-probe.txt', 'sudo -n timeout 90 docker exec $(' + container('openclaw') + ') node openclaw.mjs mcp probe ' + SERVER + ' --json')
        look('memory.txt', 'free -m; sudo -n docker ps -a --format "{{.Names}} {{.State}} {{.Status}}"; sudo -n dmesg | grep -ci "out of memory"')
        for agent in picked:
            look(agent + '-log.txt', 'sudo -n docker logs --tail 300 $(' + container(agent) + ')')
        (observed / 'connector.json').write_text(json.dumps({'connector': CONNECTOR, 'server': SERVER, 'offered': offered, 'rows': rows}, indent=1))
        assert guest('sudo -n dmesg | grep -ci "out of memory" || true').strip() == '0', 'The guest ran out of memory: see observed/memory.txt'
        for agent in picked:
            assert rows[agent]['connectors'] == CONNECTOR + ' (Context7)', agent + ' was not started with the connector: ' + repr(rows[agent]['connectors'])
            theirs = sorted(set(re.findall(r'[A-Za-z0-9_-]*' + SERVER + r'[A-Za-z0-9_-]*', ' '.join(offered[agent]) + ' ' + found[agent])) - {SERVER})
            assert theirs, agent + ' lists none of the connector\'s tools. It offered ' + repr(offered[agent]) + ' and its tool search answered ' + repr(found[agent][:600])
            # Nothing else arrived with them: no shell, file, browser or code tool.
            assert not [name for name in offered[agent] if name in DENIED or name.startswith('browser_')], offered[agent]
            print(f'PASS: {agent} started with the {CONNECTOR} connector and lists its tools: ' + ', '.join(theirs))
        lap('connector checked on both agents')

        # The same plan again restarts nothing.
        before = containers()
        apply(sized)
        assert containers() == before, 'An unchanged plan restarted an agent'
        print('PASS: repeat apply of the same plan: doctor green, no agent restarted')
        lap('second apply done')

        # The connector taken away: each agent is restarted, and runs without it.
        P.run(['git', 'add', '-A'], cwd=repo)
        P.run(['git', '-c', 'user.name=tester', '-c', 'user.email=tester@example.org', 'commit', '--quiet', '-m', 'plan with a connector'], cwd=repo)
        without = dict(opts, connectors=[])
        files, _ = P.plan_files(target, picked, facts, age_recipient=recipient, agents=without)
        P.generate(repo, files)
        state = apply(sized)
        after = containers()
        for agent in picked:
            assert after[agent] and after[agent] != before[agent], agent + ' was not restarted when its settings changed'
            assert A.metadata(state, agent)['connectors'] == 'none', agent + ' still has the connector'
            assert not [name for name in answer(agent) if SERVER in name] and SERVER not in listed(agent), agent + ' still lists the connector\'s tools'
            # The env file is written whole on each apply: root's, private, and holding what the plan has.
            owner, names = guest("sudo -n sh -c 'stat -c \"%U %a\" /opt/bromigos-agents/" + agent + ".env; cut -d= -f1 /opt/bromigos-agents/" + agent + ".env | sort | tr \"\\n\" \" \"'").split('\n', 1)
            assert owner == 'root 600' and set(names.split()) == set(A.environment(agent, without, values[agent + '-env'])), (owner, names)
            print('PASS: ' + agent + ' restarted without the connector and still answers')
        lap('third apply done: connector removed')

        found = False
        for credential in [v for d in values.values() for v in d.values()]:
            assert credential not in capture.getvalue()
            for path in repo.rglob('*'):
                if path.is_file() and '.git' not in path.parts:
                    assert credential.encode() not in path.read_bytes()
            found = found or any(credential in path.read_text(errors='replace') for path in observed.iterdir())
        print('PASS: doctor, ciphertext-only repository and no credential logs; no messaging gateways enabled')
        print('NOTE: a test credential appears in what the agents printed (observed/)' if found else 'PASS: no test credential in the agents\' own output')
    finally:
        if target and target.get('known_hosts'):
            for agent in ('hermes', 'openclaw'):                  # kept for whoever reads a failed run
                look(agent + '-log-at-end.txt', 'sudo -n docker logs --tail 300 $(' + container(agent) + ')')
            look('memory-at-end.txt', 'free -m; sudo -n docker ps -a --format "{{.Names}} {{.State}} {{.Status}}"; sudo -n dmesg | grep -i "out of memory" | tail -5')
        subprocess.run([sys.executable, harness, 'destroy'], env=env, check=False)
        age_key.unlink(missing_ok=True)
        lap('finished')
        print('VM stopped; disk, SSH key and age identity removed. What the guest showed is in ' + str(observed))


if __name__ == '__main__':
    main()
