#!/usr/bin/env python3
"""Fresh Debian, real Hermes/OpenClaw images, stub inference, no external bots."""
import contextlib
import io
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'homelab/lib'), str(ROOT / 'lib')]
os.environ['BROMIGOS_LAB_PROFILES'] = str(ROOT / 'homelab/share/lab/profiles.toml')
from bromigos_homelab import provision as P, agentprovision as A

STUB = '''import json,time
from http.server import BaseHTTPRequestHandler,HTTPServer
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args): pass
 def do_GET(self):
  self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(json.dumps({'data':[{'id':'test-model','object':'model','owned_by':'test'}]}).encode())
 def do_POST(self):
  q=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
  self.send_response(200); self.send_header('Content-Type','text/event-stream' if q.get('stream') else 'application/json'); self.end_headers()
  base={'id':'test-completion','object':'chat.completion','created':int(time.time()),'model':'test-model'}
  if q.get('stream'):
   for delta,finish in [({'role':'assistant','content':'Agent test passed.'},None),({},'stop')]:
    d={**base,'object':'chat.completion.chunk','choices':[{'index':0,'delta':delta,'finish_reason':finish}]}
    self.wfile.write(('data: '+json.dumps(d)+'\\n\\n').encode()); self.wfile.flush()
   self.wfile.write(b'data: [DONE]\\n\\n')
  else:
   self.wfile.write(json.dumps({**base,'choices':[{'index':0,'message':{'role':'assistant','content':'Agent test passed.'},'finish_reason':'stop'}],'usage':{'prompt_tokens':10,'completion_tokens':4,'total_tokens':14}}).encode())
HTTPServer(('0.0.0.0',8000),Handler).serve_forever()
'''


def main():
    original_home = Path.home()
    base = Path(os.environ.get('BROMIGOS_AGENT_TEST_DIR', original_home / '.cache/bromigos-agents-e2e'))
    if base.exists():
        raise SystemExit('Use a new BROMIGOS_AGENT_TEST_DIR')
    base.mkdir(parents=True)
    sandbox = base / 'home'
    sandbox.mkdir()
    for key in list(os.environ):
        if key.startswith('VAULT_') or key in ('KUBECONFIG', 'BROMIGOS_HOMELAB_CONFIG', 'SSH_AUTH_SOCK'):
            os.environ.pop(key, None)
    os.environ.update(HOME=str(sandbox), XDG_CONFIG_HOME=str(sandbox / '.config'), XDG_DATA_HOME=str(sandbox / '.local/share'), XDG_CACHE_HOME=str(sandbox / '.cache'))
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    env = dict(os.environ, BROMIGOS_VM_DIR=str(base / 'vm'), BROMIGOS_VM_PORT=str(port), BROMIGOS_VM_OWNER=str(os.getpid()), BROMIGOS_PROVISION_IMAGE=os.environ.get('BROMIGOS_PROVISION_IMAGE', str(original_home / '.cache/bromigos-provision-debian-final/vm/debian-12-genericcloud-amd64.qcow2')))
    if not Path(env['BROMIGOS_PROVISION_IMAGE']).exists() and not os.environ.get('BROMIGOS_PROVISION_IMAGE'):
        env.pop('BROMIGOS_PROVISION_IMAGE')
    harness = str(ROOT / 'test/vm/lab-vm.py')
    age_key = base / 'age.key'
    capture = io.StringIO()
    try:
        subprocess.run([sys.executable, harness, 'up'], env=env, check=True)
        target = {'kind': 'ssh', 'ssh': 'tester@127.0.0.1', 'port': port, 'identity': str(base / 'vm/id_ed25519')}
        known = base / 'known_hosts'
        known.write_text(subprocess.check_output(['ssh-keyscan', '-p', str(port), '127.0.0.1'], stderr=subprocess.DEVNULL, text=True))
        target['known_hosts'] = str(known)
        repo = base / 'lab'
        facts = P.inventory(target)
        recipient = subprocess.run(['age-keygen', '-o', str(age_key)], capture_output=True, text=True, check=True).stderr.split('Public key: ')[1].strip()
        os.environ['SOPS_AGE_KEY_FILE'] = str(age_key)
        os.environ['XDG_CONFIG_HOME'] = str(base / 'home/.config')
        os.environ['BROMIGOS_HOMELAB_CONFIG'] = str(base / 'home/.config/bromigos/homelab.toml')
        opts = {'endpoint': 'http://lab-model-host:8000/v1', 'model': 'test-model', 'profile': 'assistant', 'tools': 'none', 'gateways': []}
        files, _ = P.plan_files(target, ['hermes', 'openclaw'], facts, age_recipient=recipient, agents=opts)
        P.generate(repo, files)
        values = {a + '-env': {'LLM_API_KEY': secrets.token_urlsafe(32), 'AGENT_API_KEY': secrets.token_urlsafe(32)} for a in ('hermes', 'openclaw')}
        P.encrypt(repo, recipient, values)
        fixture = [P.task('Install isolated stub', 'ansible.builtin.copy', {'content': STUB, 'dest': '/opt/lab-test-model.py', 'mode': '0600'}),
                   P.task('Install stub unit', 'ansible.builtin.copy', {'content': '[Unit]\nDescription=Throwaway model stub\n[Service]\nExecStart=/usr/bin/python3 /opt/lab-test-model.py\n[Install]\nWantedBy=multi-user.target\n', 'dest': '/etc/systemd/system/lab-test-model.service'}),
                   P.task('Start isolated stub', 'ansible.builtin.systemd', {'name': 'lab-test-model', 'state': 'started', 'daemon_reload': True})]
        fixture_path = base / 'fixture.json'
        fixture_path.write_text(P.dump([{'hosts': 'all', 'become': True, 'gather_facts': False, 'tasks': fixture}]))
        P.run(['ansible-playbook', '-i', str(repo / 'ansible/inventory/hosts.json'), str(fixture_path)], env=dict(os.environ, ANSIBLE_NO_LOG='true'))
        with mock.patch('builtins.input', return_value='yes'), contextlib.redirect_stdout(capture):
            P.apply(repo)
        state = json.loads((repo / 'plan.json').read_text())
        A.verify(state)
        doctor = json.loads(P.run([str(ROOT / 'homelab/bin/bromigos-lab'), 'doctor', '--json']))
        assert not doctor['summary'].get('fail') and not doctor['summary'].get('warn')
        tool_check = ['python3', '-c', "import os,json,urllib.request; r=urllib.request.Request('http://127.0.0.1:8642/v1/toolsets',headers={'Authorization':'Bearer '+os.environ['API_SERVER_KEY']}); d=json.load(urllib.request.urlopen(r,timeout=20)); assert not any(x['enabled'] and x['name'] in ('terminal','file','browser','code_execution') for x in d['data']); print('tool policy verified')"]
        import shlex
        assert P.run(P.ssh_args(target) + ['sudo -n docker exec $(sudo -n docker ps -q --filter label=com.docker.compose.service=hermes) ' + shlex.join(tool_check)]).strip() == 'tool policy verified'
        for agent in ('hermes', 'openclaw'):
            # Request from inside the container, with its own key; no key in argv.
            if agent == 'hermes':
                argv = ['python3', '-c', "import os,json,urllib.request; r=urllib.request.Request('http://127.0.0.1:8642/v1/chat/completions',data=json.dumps({'model':'test-model','messages':[{'role':'user','content':'Say the test phrase.'}],'stream':False}).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+os.environ['API_SERVER_KEY']}); d=json.load(urllib.request.urlopen(r,timeout=120)); assert 'Agent test passed' in d['choices'][0]['message']['content']; print('answer verified')"]
            else:
                argv = ['node', '-e', "fetch('http://127.0.0.1:18789/v1/chat/completions',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+process.env.AGENT_API_KEY},body:JSON.stringify({model:'openclaw:assistant',messages:[{role:'user',content:'Say the test phrase.'}],stream:false})}).then(async r=>{const d=await r.json();if(!r.ok||!JSON.stringify(d).includes('Agent test passed'))process.exit(1);console.log('answer verified')}).catch(()=>process.exit(1))"]
            import shlex
            command = 'sudo -n docker exec $(sudo -n docker ps -q --filter label=com.docker.compose.project=bromigos-agents --filter label=com.docker.compose.service=' + agent + ') ' + shlex.join(argv)
            assert P.run(P.ssh_args(target) + [command]).strip() == 'answer verified'
            print('PASS: ' + agent + ' health, metadata and real agent response against isolated stub')
        with mock.patch('builtins.input', return_value='yes'), contextlib.redirect_stdout(capture):
            P.apply(repo)
        for credential in [v for d in values.values() for v in d.values()]:
            assert credential not in capture.getvalue()
            for path in repo.rglob('*'):
                if path.is_file() and '.git' not in path.parts:
                    assert credential.encode() not in path.read_bytes()
        print('PASS: repeat apply, doctor, ciphertext-only repository and no credential logs; no messaging gateways enabled')
    finally:
        subprocess.run([sys.executable, harness, 'destroy'], env=env, check=False)
        age_key.unlink(missing_ok=True)
        print('VM stopped; disk, SSH key and age identity removed')


if __name__ == '__main__':
    main()
