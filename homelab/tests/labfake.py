"""A lab made of recorded API answers (fixtures/lab.json), for the console, doctor, models and
queue tests: a homelab.toml of seven sources (Prometheus with node-exporter, DCGM, Argo CD's
and LiteLLM's metrics; a kubernetes source; Argo CD through the metrics; LiteLLM; Vault; the
voice service; ComfyUI) plus an Ollama that doesn't answer. Every HTTP call and kubectl run
is answered from the recording; nothing reaches a network.

    with labfake.Lab() as lab:            # a temporary homelab.toml and state folder
        lab.http["comfyui"]["/queue"] = {...}   # change an answer
        lab.down.add("voice")             # make a source unreachable
        console.status()

The answers were recorded from a real lab (a 5090 running ComfyUI and the voice service, three
DGX Sparks serving vLLM, Argo CD, Prometheus) and scrubbed: generic host names, TEST-NET
addresses, private apps left out.
"""
import copy
import json
import os
import tempfile
import urllib.parse
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCES = """
[[source]]
name = "prometheus"
type = "prometheus"
endpoint = "https://prometheus.lab.example"

[[source]]
name = "k3s"
type = "kubernetes"
context = "lab"

[[source]]
name = "argocd"
type = "argocd"

[[source]]
name = "litellm"
type = "litellm"
endpoint = "https://litellm.lab.example"

[[source]]
name = "vault"
type = "vault"
endpoint = "https://vault.lab.example"

[[source]]
name = "voice"
type = "bromigos-voice"
endpoint = "https://tts.lab.example"

[[source]]
name = "comfyui"
type = "comfyui"
endpoint = "http://comfyui.lab.example:8188"

[[source]]
name = "ollama"
type = "ollama"
endpoint = "http://gpu-box.lab.example:11434"
"""


def fixture():
    with open(os.path.join(HERE, "fixtures", "lab.json")) as f:
        return json.load(f)


class Lab:
    def __init__(self, extra_toml=""):
        fx = fixture()
        self.http = copy.deepcopy(fx["http"])
        self.kubectl = dict(fx["kubectl"])
        self.down = {"ollama"}
        self.posts = []          # (source, path, data) of every POST
        self.extra = extra_toml
        self._patches = []

    def _answer(self, adapter, path, data=None, method=None, timeout=8, headers=None, raw=False):
        from bromigos_homelab.registry import Unreachable
        name = adapter.name
        if name in self.down:
            raise Unreachable(f"{name}: [Errno 111] Connection refused")
        if method == "POST" or data is not None:
            self.posts.append((name, path, data))
            return b"{}" if raw else {}
        key = path
        if path.startswith("/api/v1/query_range?"):
            q = urllib.parse.parse_qs(path.split("?", 1)[1])
            key = "/api/v1/query_range?" + urllib.parse.urlencode({"query": q["query"][0], "step": q.get("step", ["60"])[0]})
        m = self.http.get(name) or {}
        if key not in m:
            if path.startswith("/api/v1/query"):        # a query the recording doesn't have: no data
                v = {"status": "success", "data": {"resultType": "vector", "result": []}}
            else:
                raise Unreachable(f"{name}: no recorded answer for {path}")
        else:
            v = m[key]
        if isinstance(v, dict) and "__error__" in v:
            raise Unreachable(f"{name}: {v['__error__']}")
        if isinstance(v, dict) and "__raw__" in v:
            return v["__raw__"].encode() if raw else json.loads(v["__raw__"])
        return json.dumps(v).encode() if raw else copy.deepcopy(v)

    def _kubectl(self, adapter, args, timeout=25):
        from bromigos_homelab.registry import Unreachable
        if adapter.name in self.down:
            raise Unreachable(f"{adapter.name}: Unable to connect to the server")
        key = " ".join(args)
        if key not in self.kubectl:
            raise RuntimeError(f"error: the server doesn't have a resource type ({key})")
        return self.kubectl[key]

    def __enter__(self):
        self.dir = tempfile.TemporaryDirectory(prefix="bromigos-labfake-")
        cfg = os.path.join(self.dir.name, "homelab.toml")
        with open(cfg, "w") as f:
            f.write(SOURCES + "\n" + self.extra)
        env = {"BROMIGOS_HOMELAB_CONFIG": cfg, "BROMIGOS_SHARE_DIR": os.path.join(self.dir.name, "share"),
               "BROMIGOS_HOMELAB_PLUGINS": os.path.join(self.dir.name, "plugins"),
               "XDG_DATA_HOME": os.path.join(self.dir.name, "data"),
               "BROMIGOS_LAB_STATE": os.path.join(self.dir.name, "state"),
               "BROMIGOS_LAB_OUT": os.path.join(self.dir.name, "out"), "BROMIGOS_LAB_NOTIFY": "off",
               "BROMIGOS_LAB_NO_SYSTEMD": "1", "VAULT_ADDR": ""}
        self._patches = [mock.patch.dict(os.environ, env)]
        from bromigos_homelab import config, registry
        from bromigos_homelab.adapters import kube
        self._patches += [mock.patch.object(registry.Adapter, "request",
                                            lambda a, path, data=None, method=None, timeout=8, headers=None, raw=False:
                                            self._answer(a, path, data, method, timeout, headers, raw)),
                          mock.patch.object(kube, "_kubectl_for", self._kubectl),
                          mock.patch("shutil.which", lambda name, *a, **k: "/usr/bin/kubectl" if name == "kubectl" else None)]
        for p in self._patches:
            p.start()
        config.USER = cfg
        config.PANELS_DIR = os.path.join(self.dir.name, "panels")
        config._cache.update(sig=None, data={}, errors=[])
        registry._inst.update(sig=None, list=[])
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()
        from bromigos_homelab import config, registry
        config.USER = os.environ.get("BROMIGOS_HOMELAB_CONFIG") or os.path.join(
            os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "bromigos", "homelab.toml")
        config._cache.update(sig=None, data={}, errors=[])
        registry._inst.update(sig=None, list=[])
        self.dir.cleanup()
        return False
