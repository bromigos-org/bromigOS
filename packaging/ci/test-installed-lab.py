"""Exercise the installed package with a loopback fake service and a headless terminal."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading

class Fake(BaseHTTPRequestHandler):
    requests = set()
    def log_message(self, *args): pass
    def do_GET(self):
        self.requests.add(self.path)
        if self.path in ('/api/tags', '/api/ps'):
            body = json.dumps({'models': []}).encode()
            self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers(); self.wfile.write(body)
        else: self.send_error(404)

async def screen():
    from bromigos_homelab.tui import LabApp
    from textual.widgets import TabbedContent, Tree
    app = LabApp(interval=999)
    async with app.run_test(size=(120, 40)) as pilot:
        tabs = app.query_one('#tabs', TabbedContent)
        for tab in app.TABS:
            tabs.active = tab
            await pilot.pause(.1)
            assert tabs.active == tab
            field = {'status': 'doc', 'models': 'inv', 'jobs': 'jobsdoc', 'doctor': 'doctor_doc'}.get(tab)
            if field:
                for _ in range(100):
                    if getattr(app, field) is not None: break
                    await pilot.pause(.1)
                assert getattr(app, field) is not None, tab
        assert app.doc['configured']
        assert list(app.query(Tree))
        await pilot.press('ctrl+q')

with tempfile.TemporaryDirectory(prefix='lab-installed-') as temp:
    os.environ['HOME'] = temp
    os.environ['XDG_CONFIG_HOME'] = temp + '/config'
    os.environ['XDG_STATE_HOME'] = temp + '/state'
    os.environ['XDG_CACHE_HOME'] = temp + '/cache'
    server = ThreadingHTTPServer(('127.0.0.1', 0), Fake)
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    config = Path(temp) / 'homelab.toml'
    config.write_text('[[source]]\nname="test-models"\ntype="ollama"\nendpoint="http://127.0.0.1:' + str(server.server_port) + '"\n')
    os.environ['BROMIGOS_HOMELAB_CONFIG'] = str(config)
    try:
        assert not shutil.which('bromigos')
        help_text = subprocess.check_output(['bromigos-lab', '--help'], text=True)
        assert 'bromigos-lab' in help_text
        result = json.loads(subprocess.check_output(['bromigos-lab', 'doctor', '--json'], text=True))
        assert result['summary']['fail'] == 0, result['summary']
        assert result['configured'] and 'sources' in result['checks']
        assert '/api/tags' in Fake.requests
        subprocess.run(['bromigos-lab', 'doctor'], check=True)
        subprocess.run(['/usr/lib/bromigos/bin/bromigos-lab', '--help'], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(['bromigos-lab', 'models', 'check'], check=True)
        from bromigos_homelab import catalog, services
        assert '/usr/share/bromigos-lab/models.toml' in catalog.candidates_paths()
        assert catalog.load()
        from bromigos_homelab import catalog_refresh
        assert catalog_refresh.KEYRING == '/usr/share/bromigos-lab/bromigos.gpg'
        key = Path(catalog_refresh.KEYRING)
        assert key.is_file() and key.stat().st_size > 0
        keys = subprocess.check_output(['gpg', '--batch', '--with-colons', '--show-keys', str(key)], text=True, stderr=subprocess.DEVNULL)
        assert '393E7D54F7DE58FE75B97214947C9D6193D3DD8B' in keys
        assert services.load()
        from bromigos_homelab import infrastructure, vmproviders, agentprovision
        asyncio.run(screen())
        print('PASS: installed CLI, fake doctor, bundled catalogs, provisioning imports and all five TUI tabs')
    finally:
        server.shutdown(); server.server_close(); worker.join()
