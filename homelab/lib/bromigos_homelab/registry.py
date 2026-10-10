"""Adapters: the code that talks to one kind of service and provides capabilities.

An adapter is a subclass of Adapter registered under its type:

    from bromigos_homelab.registry import Adapter, register

    @register
    class Netdata(Adapter):
        type = "netdata"
        provides = ("metrics", "hosts")
        default_ports = (19999,)                     # for `bromigos setup homelab`

        def probe(self):                             # is <endpoint> one of these?
            return "version" in self.get_json("/api/v1/info", timeout=3)

        def hosts(self):                             # capability methods: caps.py has the schemas
            info = self.get_json("/api/v1/info")
            return [{"name": info["mirrored_hosts"][0], "up": True, ...}]

bromigOS's adapters are in adapters/. Third-party ones are Python files in
~/.config/bromigos/plugins/homelab/ (or $BROMIGOS_HOMELAB_PLUGINS), then installed
extensions' (~/.local/share/bromigos/ext/active/homelab: bromigos ext), loaded once; an
adapter that fails to load is skipped and named in ERRORS (bromigos homelab status shows it).
"""
import glob
import importlib.util
import json
import os
import ssl
import sys
import urllib.error
import urllib.request

from . import config

ADAPTERS = {}          # type -> class
ERRORS = []            # (where, "Type: message")
CAPABILITIES = ("metrics", "hosts", "workloads", "deployments", "models", "agents", "secrets", "ci", "alerts", "voice", "media",
                # the lab's own services (adapters/lab*.py; docs/homelab.md, "Adapters")
                "gpus", "logs", "routes", "certs", "ddns", "network", "storage", "apps", "games", "library",
                "runners", "packages", "backups", "ocr", "energy", "youtube-downloader")
EXTRAS = {"snapshot", "knowledge"}     # a whole-lab snapshot (lab); a memory/knowledge service (gnosis)


def register(cls):
    if not getattr(cls, "type", None):
        raise ValueError(f"{cls.__name__}: an adapter needs a type")
    unknown = set(cls.provides) - set(CAPABILITIES) - EXTRAS
    if unknown:
        raise ValueError(f"{cls.type}: unknown capabilities {sorted(unknown)}")
    ADAPTERS.setdefault(cls.type, cls)        # the first registration wins: a plugin can't replace one
    return cls


class Unreachable(OSError):
    """The source didn't answer (shown as 'unreachable', never a crash)."""


class Adapter:
    type = ""
    provides = ()               # capabilities this adapter can provide
    default_ports = ()          # well-known ports, for setup's probing
    default_scheme = "http"
    local = False               # needs no endpoint (a CLI or a socket on this machine)

    def __init__(self, source):
        self.source = source
        self.name = source.get("name") or self.type
        self.endpoint = (source.get("endpoint") or "").rstrip("/")
        self.opts = source
        want = source.get("provides")
        self.caps = tuple(c for c in (want or self.provides) if c in self.provides)

    # ---- set up
    def configured(self):
        return bool(self.endpoint) or self.local

    def probe(self):
        """True when the endpoint is this kind of service (setup's auto-detection)."""
        return False

    # ---- HTTP, with the source's CA and auth_ref
    def _ctx(self):
        ca = config.expand(self.opts.get("tls_ca") or config.setting("tls", "ca_file", ""))
        if ca and os.path.isfile(ca):
            return ssl.create_default_context(cafile=ca)
        if self.opts.get("tls_verify") is False:
            c = ssl.create_default_context()
            c.check_hostname = False
            c.verify_mode = ssl.CERT_NONE
            return c
        return ssl.create_default_context()

    def auth_headers(self):
        ref = self.opts.get("auth_ref")
        if not ref:
            return {}
        tok = config.resolve(ref)
        if not tok:
            return {}
        header = self.opts.get("auth_header") or "Authorization"
        scheme = self.opts.get("auth_scheme", "Bearer")
        return {header: f"{scheme} {tok}".strip()}

    def request(self, path, data=None, method=None, timeout=8, headers=None, raw=False):
        url = path if path.startswith(("http://", "https://")) else self.endpoint + path
        h = dict(self.auth_headers(), **(headers or {}))
        body = json.dumps(data).encode() if data is not None else None
        if body is not None:
            h.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(url, data=body, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=self._ctx()) as r:
                b = r.read()
        except urllib.error.HTTPError:
            raise
        except (OSError, ValueError) as e:
            raise Unreachable(f"{self.name}: {e}") from None
        return b if raw else json.loads(b or b"null")

    def get_json(self, path, timeout=8, **kw):
        return self.request(path, timeout=timeout, **kw)

    def __repr__(self):
        return f"<{self.type} {self.name}>"


# installed extensions' adapters (`bromigos ext`; docs/extensions.md), after the user's
EXT = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"),
                   "bromigos", "ext", "active", "homelab")


def load_plugins():
    dirs = [d for d in (os.environ.get("BROMIGOS_HOMELAB_PLUGINS") or os.path.join(
        os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "bromigos", "plugins", "homelab")).split(":") if d]
    dirs.append(EXT)
    for d in dirs:
        for f in sorted(glob.glob(os.path.join(d, "*.py"))):
            if os.path.basename(f).startswith(("_", ".")):
                continue
            name = "bromigos_homelab_plugin_" + os.path.basename(f)[:-3]
            if name in sys.modules:
                continue
            try:
                spec = importlib.util.spec_from_file_location(name, f)
                mod = importlib.util.module_from_spec(spec)
                sys.modules[name] = mod
                spec.loader.exec_module(mod)
            except Exception as e:                     # a broken plugin never takes the lab down
                sys.modules.pop(name, None)
                ERRORS.append((f, f"{type(e).__name__}: {e}"))


_inst = {"sig": None, "list": []}


def instances():
    """An adapter per configured source (rebuilt when homelab.toml changes)."""
    from . import adapters  # noqa: F401  (registers bromigOS's own)
    if not _inst.get("plugins"):
        load_plugins()
        _inst["plugins"] = True
    sig = config._sig()
    if sig != _inst["sig"]:
        out = []
        for s in config.sources():
            cls = ADAPTERS.get(s["type"])
            if not cls:
                ERRORS.append((s["name"], f"no adapter of type {s['type']!r}"))
                continue
            try:
                a = cls(s)
            except Exception as e:
                ERRORS.append((s["name"], f"{type(e).__name__}: {e}"))
                continue
            if a.configured():
                out.append(a)
        _inst.update(sig=sig, list=out)
    return _inst["list"]


def providers(cap):
    return [a for a in instances() if cap in a.caps]
