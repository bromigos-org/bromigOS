"""The operator's private values, read from the decrypted overlay.

This repo is public. LAN addresses, internal hostnames, Vault paths and the like live
encrypted in ../private.sops.yaml (sops + age). At login bromigos-private.service
decrypts it to ~/.config/bromigos/private/config.json (0600, gitignored); this module
reads that file. Without it (a fresh clone, no age key) every lookup returns the
public default the caller passes, so the desktop still runs, just without the lab.

    import sys, os; sys.path.insert(0, os.path.expanduser("~/.config/bromigos/lib"))
    import bromigos_private as P
    P.url("lab", "/api/status")      # endpoints.lab + path, or "" when unset
    P.get("lan.ping", [])            # any dotted key
    P.vault("lab_api")               # vault.paths.lab_api, or ""

Each user keeps their own keys; the module is in lib/README.md ("bromigos_private"). Add one with
`bromigos-private edit`. Real secrets (tokens, keys, kubeconfigs) never go in here:
they stay in Vault and reach ~/.local/share/bromigos/ through `bromigos-secrets sync`.
"""
import json
import os

PATH = os.environ.get("BROMIGOS_PRIVATE_CONFIG") or os.path.expanduser("~/.config/bromigos/private/config.json")
_cache = {"mtime": None, "data": {}}


def data():
    """The whole overlay as a dict ({} when absent or unreadable). Re-read when it changes."""
    try:
        m = os.stat(PATH).st_mtime
    except OSError:
        _cache.update(mtime=None, data={})
        return {}
    if m != _cache["mtime"]:
        try:
            with open(PATH) as f:
                d = json.load(f)
            _cache.update(mtime=m, data=d if isinstance(d, dict) else {})
        except (OSError, ValueError):
            _cache.update(mtime=m, data={})
    return _cache["data"]


def present():
    return bool(data())


def get(key, default=None):
    """Dotted lookup: get("netmap.gateway.ip", "")."""
    cur = data()
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return default if cur is None else cur


def url(name, path="", default=""):
    """endpoints.<name> with path appended; default when the endpoint isn't configured."""
    base = get("endpoints." + name, "")
    if not base:
        return default
    return base.rstrip("/") + path if path else base


def vault(name, default=""):
    """A Vault path by role name (vault.paths.<name>), e.g. vault("lab_api")."""
    return get("vault.paths." + name, default)


def vault_root(default=""):
    """The KV prefix VECTOR's Vault tools may touch (vault.root)."""
    return get("vault.root", default)


def lan_domain(default=""):
    """The internal DNS suffix (lan.domain), e.g. for 'internal hosts allowed' checks."""
    return get("lan.domain", default)


def path(name, default=""):
    """paths.<name>, with ~ expanded."""
    p = get("paths." + name, default)
    return os.path.expanduser(p) if p else p
