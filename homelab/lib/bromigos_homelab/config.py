"""homelab.toml: the homelab's sources, which capabilities they provide, and declared panels.

    /usr/share/bromigos/default/homelab.toml   documented, no sources
    ~/.config/bromigos/homelab.toml            the user's (written by `bromigos setup homelab`
                                               or by hand)
    ~/.config/bromigos/homelab/panels/*.toml   more [[panel]]s, one file each if you like

$BROMIGOS_HOMELAB_CONFIG replaces the user's file; $BROMIGOS_SHARE_DIR the /usr/share root.
Files are re-read when they change.

A source:

    [[source]]
    name = "prometheus"                      # unique; defaults to type
    type = "prometheus"                      # an adapter (bromigos homelab adapters lists them)
    endpoint = "@private:endpoints.prometheus"
    auth_ref = "@file:~/.local/share/bromigos/prom-token"   # optional
    tls_ca = "~/.config/homelab/homelab-ca.crt"             # optional
    provides = ["metrics", "alerts"]         # optional: limit or add capabilities
    enabled = true
    # anything else is the adapter's own option (kubeconfig, orgs, namespace, …)

References, so a homelab.toml can sit in a public repo with nothing private in it:
    "@private:endpoints.prometheus"   the private overlay (bromigos_private), a dotted key
    "@env:NAME"                       an environment variable
    "@file:~/path"                    a file's content, stripped (a 0600 token file)
    "@vault:kv/path#field"            Vault, through the `vault` CLI and its login (cached)
A reference that doesn't resolve is "" and the source stays off. Secrets are only ever
references (auth_ref), never values in the file.
"""
import glob
import os
import subprocess
import time
import tomllib

_CONFIG = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
SHARE = os.environ.get("BROMIGOS_SHARE_DIR") or "/usr/share/bromigos"
DEFAULT = os.path.join(SHARE, "default", "homelab.toml")
HERE_DEFAULT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))),
                            "share", "homelab.toml")            # running from a bromigOS checkout
USER = os.environ.get("BROMIGOS_HOMELAB_CONFIG") or os.path.join(_CONFIG, "bromigos", "homelab.toml")
PANELS_DIR = os.path.join(os.path.dirname(USER), "homelab", "panels")

_cache = {"sig": None, "data": {}, "errors": []}
_vault = {}


def _files():
    return [DEFAULT if os.path.isfile(DEFAULT) else HERE_DEFAULT, USER] + sorted(glob.glob(os.path.join(PANELS_DIR, "*.toml")))


def _sig():
    out = []
    for p in _files():
        try:
            st = os.stat(p)
            out.append((p, st.st_mtime_ns, st.st_size))
        except OSError:
            out.append((p, None))
    return tuple(out)


def load():
    """{"settings": {...}, "sources": [...], "panels": [...]}, re-read when a file changes.
    Tables merge (the user's keys win); [[source]] and [[panel]] lists add up, and a user
    source or panel with the same name replaces the default's."""
    sig = _sig()
    if sig == _cache["sig"]:
        return _cache["data"]
    settings, sources, panels, errors = {}, {}, {}, []
    for p in _files():
        try:
            with open(p, "rb") as f:
                d = tomllib.load(f)
        except FileNotFoundError:
            continue
        except (OSError, ValueError) as e:
            errors.append(f"{p}: {e}")
            continue
        for s in d.pop("source", []) or []:
            if isinstance(s, dict) and s.get("type"):
                sources[s.get("name") or s["type"]] = s
        for pn in d.pop("panel", []) or []:
            if isinstance(pn, dict) and pn.get("name"):
                panels[pn["name"]] = dict(pn, _file=p)
        for k, v in d.items():
            settings[k] = dict(settings.get(k, {}), **v) if isinstance(v, dict) and isinstance(settings.get(k), dict) else v
    data = {"settings": settings, "sources": list(sources.values()), "panels": list(panels.values())}
    _cache.update(sig=sig, data=data, errors=errors)
    return data


def errors():
    load()
    return list(_cache["errors"])


def _private():
    try:
        import bromigos_private
        return bromigos_private
    except ImportError:
        return None


def _vault_field(ref):
    """kv/path#field through the vault CLI (its own login), cached 10 minutes."""
    hit = _vault.get(ref)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    path, _, field = ref.partition("#")
    val = ""
    if path and field:
        try:
            p = subprocess.run(["vault", "kv", "get", "-field=" + field, path], capture_output=True, text=True, timeout=8)
            val = p.stdout.strip() if p.returncode == 0 else ""
        except (OSError, subprocess.TimeoutExpired):
            val = ""
    _vault[ref] = (time.time(), val)
    return val


def resolve(v):
    """A value with its references resolved (recursively through lists and tables)."""
    if isinstance(v, str):
        if v.startswith("@private:"):
            P = _private()
            r = P.get(v[len("@private:"):], "") if P else ""
            return resolve(r) if isinstance(r, (str, list, dict)) else r
        if v.startswith("@env:"):
            return os.environ.get(v[len("@env:"):], "")
        if v.startswith("@file:"):
            try:
                with open(os.path.expanduser(v[len("@file:"):])) as f:
                    return f.read().strip()
            except OSError:
                return ""
        if v.startswith("@vault:"):
            return _vault_field(v[len("@vault:"):])
        return v
    if isinstance(v, list):
        return [resolve(x) for x in v]
    if isinstance(v, dict):
        return {k: resolve(x) for k, x in v.items()}
    return v


def setting(table, key, default=None):
    v = resolve((load()["settings"].get(table) or {}).get(key))
    return default if v in (None, "") else v


def table(name):
    """A whole settings table ([netmap], [services], …), references resolved ({} when absent)."""
    t = load()["settings"].get(name)
    return resolve(t) if isinstance(t, dict) else {}


def sources():
    """The configured sources, references resolved except auth_ref (resolved by the adapter
    at call time, so a secret never sits in a long-lived dict)."""
    out = []
    for s in load()["sources"]:
        if s.get("enabled") is False:
            continue
        r = {k: (v if k == "auth_ref" else resolve(v)) for k, v in s.items()}
        r.setdefault("name", r["type"])
        out.append(r)
    return out


def panels():
    return [resolve(p) for p in load()["panels"]]


def expand(p):
    return os.path.expanduser(p) if isinstance(p, str) and p else ""
