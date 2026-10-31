"""bromigos lab network: your lab's own private network (docs/lab-network.md).

Your lab runs Headscale, an open-source server that does what Tailscale's coordination service
does. Machines and phones join it with the ordinary Tailscale apps, and reach each other from
anywhere, privately, with no Tailscale account. This module provisions it as a reviewed plan, the
way `bromigos lab provision` does, and runs it afterwards:

  setup    the plan: Headscale on the lab's k3s (a Helm chart) or as a Podman Quadlet on one lab
           machine; the public address (your relay, a forwarded router port, or your network only);
           sign-in (your identity provider, or local users); a default-deny access policy. It
           shows every file and step, writes the files into your lab repository, and applies only
           after an exact yes.
  join     a one-time join code (a pre-auth key, tagged for servers) as a bundle and a QR code
  connect  join THIS machine with a bundle (reach.py; the installer and Field Kit use the same)
  status   devices: online or last seen, addresses, tags; unused join codes
  approve  a phone or laptop that signed in through the Tailscale app and shows a code
  remove   a device, after you type its name
  rotate   expire every unused join code (a lost Field Kit stick), or make one device sign in again

Every verb takes --json. Nothing here knows anyone's hosts: the plan names only what you give it.
"""
import argparse
import datetime
import getpass
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

from . import reach as R

IMAGE = "docker.io/headscale/headscale:0.29.7"
VERSION = "0.29.7"
NAMESPACE = "lab-network"
CONTAINER = "headscale"
TAGS = {"server": "tag:server", "lab": "tag:lab"}
DNS_DOMAIN = "lab.home.arpa"
TAILSCALE_DERP = "https://controlplane.tailscale.com/derpmap/default"
MARK_BEGIN = "# Your lab's private network (bromigos lab network setup writes this block)\n"
MARK_END = "# end of the lab network block\n"
ENDPOINTS = {
    "relay": "On your relay (a small server on the internet you rent): Headscale runs there, with its own "
             "certificate. Your lab can be off and your devices still find each other. The most reliable.",
    "router": "Through your router: you forward one port (TCP 443) to the lab machine, and point a domain "
              "name (a dynamic DNS name works) at your home. Headscale gets its own certificate.",
    "lan": "Your network only: devices join while they're at home, and can't sign in from outside. "
           "No domain name, no ports opened.",
}


class NetError(Exception):
    pass


def say(*a):
    print(*a, flush=True)


def run(argv, data=None, check=True, timeout=300):
    """Never include a command's output in an error: it may hold a join key."""
    r = subprocess.run(argv, input=data, text=True, capture_output=True, timeout=timeout,
                       **({"stdin": subprocess.DEVNULL} if data is None else {}))
    if check and r.returncode:
        last = (r.stderr or r.stdout or "").strip().splitlines()[-1:] or ["no reason given"]
        line = re.sub(r"hskey-[A-Za-z0-9_-]+|[A-Fa-f0-9]{40,}", "…", last[0])[:200]
        raise NetError(f"{Path(argv[0]).name} {' '.join(argv[1:3])[:60]} failed (exit {r.returncode}): {line}")
    return r


# ------------------------------------------------------------------ YAML (a small emitter: the plan's files are reviewed)

def yaml(value, indent=0):
    pad = " " * indent
    if isinstance(value, dict):
        if not value:
            return "{}"
        out = []
        for k, v in value.items():
            if isinstance(v, (dict, list)) and v:
                out.append(f"{pad}{k}:\n{yaml(v, indent + 2)}")
            else:
                out.append(f"{pad}{k}: {yaml(v)}")
        return "\n".join(out)
    if isinstance(value, list):
        if not value:
            return "[]"
        out = []
        for v in value:
            if isinstance(v, dict) and v:
                inner = yaml(v, indent + 2).lstrip()
                out.append(f"{pad}- {inner}")
            else:
                out.append(f"{pad}- {yaml(v)}")
        return "\n".join(out)
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value))


# ------------------------------------------------------------------ the choices, checked

def check_domain(name):
    name = (name or "").strip().lower().rstrip(".")
    if not re.fullmatch(r"(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", name):
        raise NetError("Give the network's address as a domain name, such as net.example.org")
    return name


def check_owner(owner, oidc):
    owner = (owner or "").strip()
    if oidc:
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", owner):
            raise NetError("With your identity provider, the owner is your email address there (--owner)")
        return owner
    owner = re.sub(r"[^a-z0-9._-]", "", owner.lower())[:32]
    if not owner:
        raise NetError("Choose the owner's user name (--owner), such as your first name")
    return owner


def owner_ref(o):
    """How the policy names the owner: a local user is `name@`, an identity provider's user their email."""
    return o["owner"] if o.get("oidc") else o["owner"] + "@"


def options(a, saved=None):
    """The plan's options from the command line (or a saved plan). Every check is here."""
    o = dict(saved or {})
    for k in ("on", "endpoint", "domain", "email", "lan_address", "public_port", "derp", "owner", "node", "port",
              "identity", "known_hosts", "kubeconfig", "context", "engine", "container", "docker_network",
              "server_url", "oidc_issuer", "oidc_client_id", "oidc_secret_file", "oidc_allowed_domains", "name",
              "dns_domain", "image"):
        v = getattr(a, k, None)
        if v not in (None, "", []):
            o[k] = v
    o.setdefault("image", IMAGE)
    o.setdefault("dns_domain", DNS_DOMAIN)
    o.setdefault("name", "Your lab's network")
    o.setdefault("owner", getpass.getuser())
    o["oidc"] = bool(o.get("oidc_issuer"))
    if not o.get("on"):
        o["on"] = "k3s" if o.get("kubeconfig") else "quadlet" if o.get("node") else ""
    if o["on"] not in ("k3s", "quadlet", "dev"):
        raise NetError("Say where Headscale runs: --on k3s (with --kubeconfig and --context, or --node for a k3s "
                       "box), or --on quadlet --node user@host (a Podman machine in your lab)")
    o.setdefault("endpoint", "lan" if o["on"] == "dev" else "")
    if o["endpoint"] not in ENDPOINTS:
        raise NetError("Choose how devices reach it: --endpoint relay, router or lan")
    if o["endpoint"] == "relay" and o["on"] == "k3s":
        raise NetError("On a relay, Headscale runs on the relay itself: --on quadlet --node user@relay")
    if o["on"] in ("quadlet",) or (o["on"] == "k3s" and not o.get("kubeconfig")):
        if not re.fullmatch(r"[a-zA-Z0-9_.-]+@[a-zA-Z0-9_.:-]+", o.get("node") or ""):
            raise NetError("Give the lab machine as --node user@host (the machine Headscale runs on)")
    if o["on"] == "k3s" and o.get("kubeconfig") and not o.get("context"):
        raise NetError("Give the cluster's --context too (it never uses the current one by accident)")
    if o["endpoint"] in ("relay", "router"):
        o["domain"] = check_domain(o.get("domain"))
        o["server_url"] = "https://" + o["domain"]
        if o["dns_domain"] == o["domain"] or o["domain"].endswith("." + o["dns_domain"]):
            raise NetError("The devices' names (--dns-domain) must differ from the network's address")
    elif o["on"] == "dev":
        o.setdefault("container", "bromigos-headscale-dev")
        o.setdefault("engine", "docker")
        o.setdefault("docker_network", "bromigos-lab-network-dev")
        o["server_url"] = o.get("server_url") or f"http://{o['container']}:8080"
    else:
        try:
            ip = ipaddress.ip_address(o.get("lan_address") or "")
        except ValueError:
            raise NetError("Give the lab machine's address on your network: --lan-address, such as 192.168.1.20") from None
        if not ip.is_private or ip.is_loopback:
            raise NetError("--lan-address must be an address on your own network")
        o["server_url"] = f"http://{ip}:8080"
    o["server_url"] = R.check_server(o["server_url"])
    o["public_port"] = int(o.get("public_port") or 443)
    o.setdefault("derp", "embedded" if o["endpoint"] == "relay" else "tailscale")
    if o["derp"] not in ("tailscale", "embedded", "self"):
        raise NetError("--derp is tailscale, embedded or self")
    if o["derp"] != "tailscale" and o["endpoint"] == "lan":
        raise NetError("Your own relay (DERP) needs https: choose --endpoint relay or router for it")
    if o["oidc"]:
        if not o["oidc_issuer"].startswith("https://"):
            raise NetError("The identity provider's issuer must be an https:// address")
        o["oidc_issuer"] = R.check_server(o["oidc_issuer"])
        if not o.get("oidc_client_id"):
            raise NetError("Give your identity provider's client ID: --oidc-client-id")
        if not o.get("oidc_secret_file"):
            raise NetError("Give a file holding the client secret: --oidc-secret-file (it's sent to the lab, "
                           "never written to your lab repository)")
    o["owner"] = check_owner(o.get("owner"), o["oidc"])
    return o


# ------------------------------------------------------------------ the files

def config(o):
    """Headscale's config.yaml. No secrets: the identity provider's secret is a file beside it."""
    tls = o["endpoint"] in ("relay", "router")
    derp_urls = [] if o["derp"] == "self" else [TAILSCALE_DERP]
    doc = {
        "server_url": o["server_url"],
        "listen_addr": "0.0.0.0:443" if tls else "0.0.0.0:8080",
        "metrics_listen_addr": "127.0.0.1:9090",
        "grpc_listen_addr": "127.0.0.1:50443",
        "grpc_allow_insecure": False,
        "noise": {"private_key_path": "/var/lib/headscale/noise_private.key"},
        "prefixes": {"v4": "100.64.0.0/10", "v6": "fd7a:115c:a1e0::/48", "allocation": "sequential"},
        "derp": {"server": {"enabled": o["derp"] != "tailscale", "region_id": 999, "region_code": "lab",
                            "region_name": "Your lab", "verify_clients": True, "stun_listen_addr": "0.0.0.0:3478",
                            "private_key_path": "/var/lib/headscale/derp_server_private.key",
                            "automatically_add_embedded_derp_region": True},
                 "urls": derp_urls, "paths": [], "auto_update_enabled": bool(derp_urls), "update_frequency": "24h"},
        "disable_check_updates": True,
        "node": {"expiry": 0, "ephemeral": {"inactivity_timeout": "30m"}},
        "database": {"type": "sqlite", "sqlite": {"path": "/var/lib/headscale/db.sqlite", "write_ahead_log": True}},
        "acme_url": "https://acme-v02.api.letsencrypt.org/directory",
        "acme_email": o.get("email") or "",
        "tls_letsencrypt_hostname": o.get("domain", "") if tls else "",
        "tls_letsencrypt_cache_dir": "/var/lib/headscale/cache",
        "tls_letsencrypt_challenge_type": "TLS-ALPN-01",
        "tls_letsencrypt_listen": ":http",
        "tls_cert_path": "",
        "tls_key_path": "",
        "log": {"level": "info", "format": "text"},
        "policy": {"mode": "file", "path": "/etc/headscale/acl.hujson"},
        "dns": {"magic_dns": True, "base_domain": o["dns_domain"], "override_local_dns": False,
                "nameservers": {"global": [], "split": {}}, "search_domains": [], "extra_records": []},
        "unix_socket": "/var/run/headscale/headscale.sock",
        "unix_socket_permission": "0770",
        "logtail": {"enabled": False},
        "taildrop": {"enabled": True},
        "auto_update": {"enabled": False},
    }
    if o["oidc"]:
        doc["oidc"] = {"only_start_if_oidc_is_available": True, "issuer": o["oidc_issuer"],
                       "client_id": o["oidc_client_id"], "client_secret_path": "/etc/headscale/oidc/client_secret",
                       "scope": ["openid", "profile", "email"], "email_verified_required": True,
                       "allowed_users": [o["owner"]] + list(o.get("extra_users") or []),
                       "pkce": {"enabled": True, "method": "S256"}}
        if o.get("oidc_allowed_domains"):
            doc["oidc"]["allowed_domains"] = list(o["oidc_allowed_domains"])
    return ("# Headscale's settings, made by bromigos lab network setup (docs/lab-network.md).\n"
            "# Change them here, commit, and run setup again: it shows the difference before applying.\n"
            + yaml(doc) + "\n")


def policy(o):
    """The access policy, default-deny: only what's listed may connect."""
    owner = owner_ref(o)
    doc = {
        "groups": {"group:owners": [owner]},
        "tagOwners": {TAGS["lab"]: ["group:owners"], TAGS["server"]: ["group:owners"]},
        "acls": [
            {"action": "accept", "src": ["group:owners"],
             "dst": ["group:owners:*", TAGS["lab"] + ":*", TAGS["server"] + ":*"]},
            {"action": "accept", "src": [TAGS["lab"]], "dst": [TAGS["lab"] + ":*", TAGS["server"] + ":*"]},
        ],
    }
    body = json.dumps(doc, indent=2)
    notes = {
        '  "groups"': "  // Who owns this network. Owners' own devices (phones, laptops) belong to them.",
        '  "tagOwners"': "  // Machines carry a tag instead of an owner: tag:lab for the lab's own machines,\n"
                         "  // tag:server for other servers (bromigos lab network join gives this one).",
        '  "acls"': "  // Default deny: anything not allowed below is refused.\n"
                    "  // 1. Your devices reach each other, the lab and every server.\n"
                    "  // 2. Lab machines reach each other and the servers (monitoring, backups).\n"
                    "  // Servers reach nothing on their own, and nothing reaches your devices but you.",
    }
    for key, note in notes.items():
        body = body.replace(key, note + "\n" + key, 1)
    return ("// The lab network's access policy (HuJSON), made by bromigos lab network setup.\n"
            "// docs/lab-network.md, \"For power users\": ACLs, tags and keys.\n" + body + "\n")


def container_flags(o):
    """What the container gets, the same in the Quadlet, the dev container and (as a pod spec) on k3s."""
    tls = o["endpoint"] in ("relay", "router")
    ports = []
    if tls:
        ports.append("443:443/tcp")
    elif o["on"] == "dev":
        ports = []
    else:
        ports.append(f"{o['lan_address']}:8080:8080/tcp")
    if o["derp"] != "tailscale":
        ports.append("3478:3478/udp")
    return {"ports": ports, "read_only": True, "tmpfs": ["/var/run/headscale"], "no_new_privileges": True}


def quadlet_files(o):
    f = container_flags(o)
    unit = ["# Headscale, your lab's private network (bromigos lab network setup).",
            "[Unit]", "Description=Headscale: your lab's private network",
            "Wants=network-online.target", "After=network-online.target", "",
            "[Container]", f"Image={o['image']}", f"ContainerName={CONTAINER}", "Exec=serve",
            "Volume=/etc/headscale:/etc/headscale:ro,Z", "Volume=headscale-data.volume:/var/lib/headscale:Z"]
    unit += [f"PublishPort={p}" for p in f["ports"]]
    unit += ["ReadOnly=true"] + [f"Tmpfs={t}" for t in f["tmpfs"]] + ["NoNewPrivileges=true",
             "HealthCmd=/ko-app/headscale health", "HealthInterval=30s", "",
             "[Service]", "Restart=always", "TimeoutStartSec=300", "",
             "[Install]", "WantedBy=multi-user.target default.target", ""]
    return {"network/quadlet/headscale.container": "\n".join(unit),
            "network/quadlet/headscale-data.volume": "# Headscale's database and keys (bromigos lab network setup)\n[Volume]\n"}


def helm_files(o):
    """A small chart of our own: one Deployment, its disk, a Service and the settings."""
    tls = o["endpoint"] in ("relay", "router")
    port = 443 if tls else 8080
    svc_type = "LoadBalancer"                     # k3s's ServiceLB answers on the nodes' own addresses
    svc_port = o["public_port"] if tls else 8080
    base = "network/helm/headscale/"
    values = {"image": o["image"], "servicePort": svc_port, "containerPort": port, "serviceType": svc_type,
              "stun": o["derp"] != "tailscale", "storage": "1Gi", "oidcSecret": "headscale-oidc" if o["oidc"] else ""}
    deployment = """apiVersion: apps/v1
kind: Deployment
metadata:
  name: headscale
  labels: {app.kubernetes.io/name: headscale, app.kubernetes.io/part-of: bromigos-lab-network}
spec:
  replicas: 1
  strategy: {type: Recreate}
  selector:
    matchLabels: {app.kubernetes.io/name: headscale}
  template:
    metadata:
      labels: {app.kubernetes.io/name: headscale}
      annotations:
        checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
    spec:
      enableServiceLinks: false
      containers:
        - name: headscale
          image: {{ .Values.image | quote }}
          args: ["serve"]
          ports:
            - {name: control, containerPort: {{ .Values.containerPort }}, protocol: TCP}
            {{- if .Values.stun }}
            - {name: stun, containerPort: 3478, protocol: UDP}
            {{- end }}
          readinessProbe:
            exec: {command: ["/ko-app/headscale", "health"]}
            periodSeconds: 10
          securityContext:
            readOnlyRootFilesystem: true
            allowPrivilegeEscalation: false
          volumeMounts:
            - {name: config, mountPath: /etc/headscale, readOnly: true}
            - {name: data, mountPath: /var/lib/headscale}
            - {name: run, mountPath: /var/run/headscale}
            {{- if .Values.oidcSecret }}
            - {name: oidc, mountPath: /etc/headscale/oidc, readOnly: true}
            {{- end }}
      volumes:
        - {name: config, configMap: {name: headscale}}
        - {name: data, persistentVolumeClaim: {claimName: headscale-data}}
        - {name: run, emptyDir: {}}
        {{- if .Values.oidcSecret }}
        - {name: oidc, secret: {secretName: {{ .Values.oidcSecret | quote }}, defaultMode: 0400}}
        {{- end }}
"""
    service = """apiVersion: v1
kind: Service
metadata:
  name: headscale
  labels: {app.kubernetes.io/name: headscale}
spec:
  type: {{ .Values.serviceType }}
  selector: {app.kubernetes.io/name: headscale}
  ports:
    - {name: control, port: {{ .Values.servicePort }}, targetPort: control, protocol: TCP}
    {{- if .Values.stun }}
    - {name: stun, port: 3478, targetPort: stun, protocol: UDP}
    {{- end }}
"""
    configmap = """apiVersion: v1
kind: ConfigMap
metadata:
  name: headscale
data:
  config.yaml: |
{{ .Files.Get "files/config.yaml" | indent 4 }}
  acl.hujson: |
{{ .Files.Get "files/acl.hujson" | indent 4 }}
"""
    pvc = """apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: headscale-data
  annotations: {helm.sh/resource-policy: keep}
spec:
  accessModes: [ReadWriteOnce]
  resources: {requests: {storage: {{ .Values.storage }}}}
"""
    return {base + "Chart.yaml": f"apiVersion: v2\nname: headscale-lab\ndescription: Headscale, your lab's private "
                                  f"network (bromigos lab network setup)\ntype: application\nversion: 0.1.0\n"
                                  f"appVersion: \"{VERSION}\"\n",
            base + "values.yaml": "# Made by bromigos lab network setup; run setup again after changing it.\n" + yaml(values) + "\n",
            base + "templates/deployment.yaml": deployment, base + "templates/service.yaml": service,
            base + "templates/configmap.yaml": configmap, base + "templates/pvc.yaml": pvc,
            base + "files/config.yaml": config(o), base + "files/acl.hujson": policy(o)}


def target_of(o):
    """How to reach the lab machine or cluster (no secrets): saved in network.json."""
    if o["on"] == "dev":
        return {"kind": "dev", "engine": o["engine"], "container": o["container"], "network": o["docker_network"]}
    if o["on"] == "k3s" and o.get("kubeconfig"):
        return {"kind": "kubectl", "kubeconfig": str(Path(o["kubeconfig"]).expanduser().resolve()), "context": o["context"]}
    t = {"kind": "ssh" if o["on"] == "quadlet" else "k3s-ssh", "ssh": o["node"], "port": int(o.get("port") or 22)}
    if o.get("identity"):
        t["identity"] = str(Path(o["identity"]).expanduser().resolve())
    if o.get("known_hosts"):
        t["known_hosts"] = str(Path(o["known_hosts"]).expanduser().resolve())
    return t


def steps(o, repo):
    """What apply does, in order: (words, the command shown). The plan prints all of them."""
    t = target_of(o)
    net = Path(repo) / "network"
    s = []
    if o["on"] == "quadlet":
        node = f"{t['ssh']}"
        s += [("Make Headscale's settings folder on " + node, "sudo install -d -m 0750 /etc/headscale"),
              ("Copy its settings and access policy there", "/etc/headscale/config.yaml, /etc/headscale/acl.hujson (0640)")]
        if o["oidc"]:
            s.append(("Copy your identity provider's client secret (read from " + o["oidc_secret_file"] + ", sent "
                      "over SSH, never written to the repository)", "/etc/headscale/oidc/client_secret (0600)"))
        s += [("Install the Podman Quadlet", "/etc/containers/systemd/headscale.container, headscale-data.volume"),
              ("Start it (it starts again at every boot)", "sudo systemctl daemon-reload && sudo systemctl restart headscale.service")]
    elif o["on"] == "k3s":
        where = "the cluster " + o["context"] if o.get("kubeconfig") else "k3s on " + o["node"]
        if o["oidc"]:
            s.append(("Store the client secret as a Kubernetes Secret on " + where,
                      f"kubectl -n {NAMESPACE} apply Secret headscale-oidc (from {o['oidc_secret_file']})"))
        s.append(("Install the chart on " + where,
                  f"helm upgrade --install headscale {net / 'helm/headscale'} -n {NAMESPACE} --create-namespace --wait"))
    else:
        s += [("Make the dev network", f"{o['engine']} network create {o['docker_network']}"),
              ("Start the dev container (the same settings and limits as the Quadlet)",
               f"{o['engine']} run -d --name {o['container']} --network {o['docker_network']} --read-only "
               f"-v {net}:/etc/headscale:ro {o['image']} serve")]
    s.append(("Wait for it to answer", "headscale health"))
    if not o["oidc"]:
        s.append((f"Make you its owner, the local user {o['owner']}", f"headscale users create {o['owner']}"))
    s.append(("Connect the lab console to it", "~/.config/bromigos/homelab.toml: [network]"))
    return s


def ports_words(o):
    if o["endpoint"] == "relay":
        out = ["TCP 443 open on the relay (Headscale's certificate and the network itself)"]
    elif o["endpoint"] == "router":
        out = ["On your router: forward TCP 443 to the lab machine" + (f"'s port {o['public_port']}" if o["on"] == "k3s"
               and o["public_port"] != 443 else "'s port 443"), f"{o['domain']} pointing at your home's address "
               "(a dynamic DNS name works)"]
    else:
        out = ["TCP 8080 on your network only"]
    if o["derp"] != "tailscale":
        out.append("UDP 3478 open too (your own relay's STUN)")
    return out


def plan(o, repo):
    """Everything setup will make and do: pure, so the review is exactly what applies."""
    net = "network/"
    files = {net + "config.yaml": config(o), net + "acl.hujson": policy(o)}
    if o["on"] == "quadlet":
        files.update(quadlet_files(o))
    elif o["on"] == "k3s":
        files.update(helm_files(o))
    state = {k: v for k, v in o.items() if k not in ("oidc_secret_file",)}
    state.update(version=1, target=target_of(o), oidc_secret_file=bool(o.get("oidc_secret_file")))
    files[net + "network.json"] = json.dumps(state, indent=2, sort_keys=True) + "\n"
    return {"server_url": o["server_url"], "files": files, "steps": steps(o, repo), "ports": ports_words(o),
            "notes": notes(o)}


def notes(o):
    out = []
    if o["derp"] == "tailscale":
        out.append("When two devices can't connect directly, they relay through Tailscale's public DERP servers. "
                   "That traffic stays end-to-end encrypted, and needs no account. --derp embedded runs your own.")
    if o["endpoint"] == "lan":
        out.append("Devices sign in only at home. Once joined, they keep working away from home if the lab "
                   "machine stays reachable through another path; otherwise choose a relay later.")
    if o["oidc"]:
        out.append(f"Sign-in goes to your identity provider ({o['oidc_issuer']}). Add the redirect "
                   f"{o['server_url']}/oidc/callback to its client. Only {o['owner']} may sign in until you add others.")
    else:
        out.append("Local users: a phone or laptop signing in shows a code, which you approve: "
                   "bromigos lab network approve CODE (or the lab console's NETWORK tab).")
    return out


def review(p, o, repo, out=say, changed=None, full=True):
    out(f"Your lab's private network: {o['name']}")
    out(f"  Address: {p['server_url']}")
    where = {"k3s": "the lab's k3s, as a Helm chart (namespace " + NAMESPACE + ")",
             "quadlet": "a Podman Quadlet on " + str(o.get("node")), "dev": "a local dev container"}[o["on"]]
    out(f"  Runs: Headscale {VERSION} on {where}")
    out(f"  Reached: {o['endpoint']} — {ENDPOINTS[o['endpoint']]}")
    out("  Sign-in: " + (f"your identity provider ({o['oidc_issuer']}), owner {o['owner']}" if o["oidc"]
                         else f"local users, owner {o['owner']}"))
    out("  Access: default deny. Your devices reach the lab and servers; lab machines reach each other and "
        "servers; servers reach nothing on their own.")
    out("  Ports: " + "; ".join(p["ports"]))
    out(f"Files, in {repo}:")
    for name, text in p["files"].items():
        state = "" if changed is None else "  (new or changed)" if name in changed else "  (unchanged)"
        out(f"  {name}  ({len(text.splitlines())} lines){state}")
    if full:
        for name, text in p["files"].items():
            if changed is not None and name not in changed or name.endswith("network.json"):
                continue
            out(f"\n── {name} " + "─" * max(4, 72 - len(name)))
            out(text.rstrip("\n"))
        out("")
    out("Steps:")
    for n, (words, command) in enumerate(p["steps"], 1):
        out(f"  {n}. {words}\n       {command}")
    for note in p["notes"]:
        out("Note: " + note)


# ------------------------------------------------------------------ the lab repository and homelab.toml

def default_repo():
    """The provisioned lab's repository when there is one (homelab.toml's provisioned source), else
    a folder of its own."""
    try:
        from . import config as C
        for s in C.sources():
            if s.get("type") == "provisioned" and s.get("plan"):
                return str(Path(s["plan"]).parent)
    except Exception:
        pass
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "bromigos", "lab-network")


def write_files(repo, files):
    from .provision import write
    repo = Path(repo).expanduser()
    if repo.is_symlink():
        raise NetError("The lab repository must not be a symbolic link")
    repo = repo.resolve()
    repo.mkdir(parents=True, exist_ok=True)
    if (repo / ".git").exists():
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "network"], cwd=repo, capture_output=True,
                               text=True).stdout
        if dirty.strip():
            raise NetError("Commit or save your changes under network/ in the lab repository first")
    changed = []
    for name, text in files.items():
        dest = repo / name
        if not dest.resolve().is_relative_to(repo):
            raise NetError("A plan path escapes the repository")
        old = dest.read_text() if dest.exists() else None
        if old != text:
            changed.append(name)
            write(dest, text, 0o644)
    return repo, changed


def homelab_path():
    return Path(os.environ.get("BROMIGOS_HOMELAB_CONFIG") or
                Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "bromigos" / "homelab.toml")


def save_connection(login_server, name, plan_path, bundle=None):
    """homelab.toml's [network] block: the lab console, BRODEC's chart value and the Field Kit stick
    read it. A join bundle is kept only when asked for (join --stick)."""
    from .provision import write
    path = homelab_path()
    current = path.read_text() if path.exists() else ""
    old = re.search(re.escape(MARK_BEGIN) + r".*?" + re.escape(MARK_END), current, re.S)
    if bundle is None and old:
        m = re.search(r'^join_bundle = "([^"]*)"', old.group(0), re.M)
        bundle = m.group(1) if m else None
    block = (MARK_BEGIN + "[network]\n" + f"login_server = {json.dumps(login_server)}\n" + f"name = {json.dumps(name)}\n"
             + f"plan = {json.dumps(str(plan_path))}\n"
             + (f"join_bundle = {json.dumps(bundle)}   # one use; the Field Kit stick carries it\n" if bundle else "")
             + MARK_END)
    current = current.replace(old.group(0), block) if old else current.rstrip("\n") + ("\n\n" if current.strip() else "") + block
    path.parent.mkdir(parents=True, exist_ok=True)
    write(path, current, 0o600)
    return path


def connection():
    """The lab network the console knows: homelab.toml's [network], and its saved plan."""
    import tomllib
    path = homelab_path()
    try:
        net = tomllib.loads(path.read_text()).get("network") or {}
    except (OSError, ValueError):
        net = {}
    if not net.get("plan"):
        return None
    try:
        state = json.loads(Path(net["plan"]).read_text())
    except (OSError, ValueError):
        raise NetError(f"homelab.toml's [network] plan ({net['plan']}) can't be read: run bromigos lab network setup again")
    state["plan_path"] = net["plan"]
    return state


# ------------------------------------------------------------------ the adapters: where Headscale's command runs

def ssh_args(t):
    from .provision import ssh_args as base
    return base(t)


class Control:
    """Headscale's own command, wherever it runs: `headscale … -o json` through ssh and podman,
    kubectl exec, or the dev container."""

    def __init__(self, state):
        self.state, self.t = state, state["target"]

    def prefix(self):
        t = self.t
        if t["kind"] == "dev":
            return [t.get("engine", "docker"), "exec", "-i", t["container"], "headscale"]
        if t["kind"] == "ssh":
            return ssh_args(t) + ["sudo", "-n", "podman", "exec", "-i", CONTAINER, "headscale"]
        if t["kind"] == "kubectl":
            return ["kubectl", "--kubeconfig", t["kubeconfig"], "--context", t["context"], "-n", NAMESPACE,
                    "exec", "-i", "deploy/headscale", "--", "headscale"]
        return ssh_args(t) + ["sudo", "-n", "k3s", "kubectl", "-n", NAMESPACE, "exec", "-i", "deploy/headscale",
                              "--", "headscale"]

    def hs(self, *args, json_out=True):
        argv = self.prefix() + list(args) + (["-o", "json"] if json_out else [])
        if self.t["kind"] in ("ssh", "k3s-ssh"):          # one remote command line
            argv = argv[:len(ssh_args(self.t))] + [shlex.join(argv[len(ssh_args(self.t)):])]
        out = run(argv, timeout=60).stdout
        if not json_out:
            return out
        try:
            return json.loads(out) if out.strip() else None
        except ValueError:
            raise NetError("Headscale's answer wasn't readable (is it version " + VERSION + "?)") from None


def _secs(v):
    """A protobuf timestamp in Headscale's JSON: {"seconds": …} or an RFC 3339 string."""
    if isinstance(v, dict):
        return v.get("seconds")
    if isinstance(v, str) and v:
        try:
            return datetime.datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def iso(secs):
    if not secs or secs <= 0:
        return ""
    return datetime.datetime.fromtimestamp(secs, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _g(d, *names, default=None):
    for n in names:
        if isinstance(d, dict) and d.get(n) not in (None, ""):
            return d[n]
    return default


def devices(raw, now=None):
    """Headscale's nodes as the console shows them."""
    now = now or time.time()
    out = []
    for n in raw or []:
        tags = sorted(set(_g(n, "tags", default=[]) or []) | set(_g(n, "forced_tags", "forcedTags", default=[]) or [])
                      | set(_g(n, "valid_tags", "validTags", default=[]) or []))
        user = (_g(n, "user", default={}) or {}).get("name") or ""
        last = _secs(_g(n, "last_seen", "lastSeen"))
        expiry = _secs(_g(n, "expiry"))
        online = bool(_g(n, "online", default=False))
        kind = "lab" if TAGS["lab"] in tags else "server" if TAGS["server"] in tags else "device"
        out.append({"id": int(_g(n, "id", default=0)), "name": _g(n, "given_name", "givenName", "name", default="?"),
                    "hostname": _g(n, "name", default=""), "ips": list(_g(n, "ip_addresses", "ipAddresses", default=[]) or []),
                    "user": "" if user == "tagged-devices" else user, "tags": tags, "kind": kind, "online": online,
                    "last_seen": iso(last), "seen_ago": None if online or not last else int(now - last),
                    "expires": iso(expiry) if expiry and expiry > 0 else "",
                    "expired": bool(expiry and 0 < expiry < now)})
    return sorted(out, key=lambda d: (not d["online"], d["kind"] != "device", d["name"]))


def codes(raw, now=None):
    now = now or time.time()
    out = []
    for k in raw or []:
        exp = _secs(_g(k, "expiration"))
        used = bool(_g(k, "used", default=False))
        if used and not _g(k, "reusable", default=False):
            continue
        if exp and exp < now:
            continue
        out.append({"id": int(_g(k, "id", default=0)), "tags": list(_g(k, "acl_tags", "aclTags", default=[]) or []),
                    "expires": iso(exp), "reusable": bool(_g(k, "reusable", default=False)),
                    "ephemeral": bool(_g(k, "ephemeral", default=False)),
                    "prefix": (str(_g(k, "key", default="")) or "")[:14]})
    return out


def ago(secs):
    if secs is None:
        return "online"
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if secs >= size:
            return f"{secs // size}{unit} ago"
    return "just now"


# ------------------------------------------------------------------ the verbs

def status(control=None):
    state = connection() if control is None else control.state
    if not state:
        return {"configured": False, "words": "No lab network yet: bromigos lab network setup"}
    c = control or Control(state)
    devs = devices(c.hs("nodes", "list"))
    pending = codes(c.hs("preauthkeys", "list"))
    online = sum(1 for d in devs if d["online"])
    return {"configured": True, "name": state.get("name"), "login_server": state["server_url"],
            "runs_on": state["on"], "endpoint": state["endpoint"], "owner": state.get("owner"),
            "devices": devs, "codes": pending,
            "summary": f"{len(devs)} device{'s' if len(devs) != 1 else ''}, {online} online"
                       + (f", {len(pending)} unused join code{'s' if len(pending) != 1 else ''}" if pending else "")}


def join(tag="server", expires="24h", reusable=False, ephemeral=False, control=None):
    state = connection() if control is None else control.state
    if not state:
        raise NetError("No lab network yet: bromigos lab network setup")
    if tag not in TAGS:
        raise NetError("--tag is server or lab")
    if not re.fullmatch(r"\d+[mhd]", expires):
        raise NetError("--expires is a length of time such as 30m, 24h or 7d")
    c = control or Control(state)
    args = ["preauthkeys", "create", "--tags", TAGS[tag], "--expiration", expires]
    args += ["--reusable"] if reusable else []
    args += ["--ephemeral"] if ephemeral else []
    k = c.hs(*args)
    key = (k or {}).get("key") if isinstance(k, dict) else None
    if not key:
        raise NetError("Headscale made no join code")
    exp = iso(_secs(k.get("expiration")))
    bundle = R.encode(state["server_url"], key, name=state.get("name") or "", tags=[TAGS[tag]], expires=exp)
    return {"bundle": bundle, "login_server": state["server_url"], "key": key, "tags": [TAGS[tag]], "expires": exp,
            "reusable": reusable, "ephemeral": ephemeral, "id": int(k.get("id") or 0),
            "command": f"sudo tailscale up --login-server {state['server_url']} --auth-key {key}",
            "connect": f"bromigos lab network connect {bundle}"}


def find_device(devs, what):
    what = str(what).strip()
    hits = [d for d in devs if str(d["id"]) == what or d["name"] == what or d["hostname"] == what]
    if not hits:
        raise NetError(f"No device called {what} on the lab network (bromigos lab network status lists them)")
    if len(hits) > 1:
        raise NetError(f"More than one device is called {what}: give its number (status --json shows ids)")
    return hits[0]


def remove(what, control=None):
    c = control or Control(connection() or {})
    d = find_device(devices(c.hs("nodes", "list")), what)
    c.hs("nodes", "delete", "--identifier", str(d["id"]), "--force")
    return {"removed": d, "words": f"{d['name']} is off the lab network. To bring it back, join it again."}


def rotate(device=None, control=None):
    """Without a device: expire every unused join code. With one: that device must sign in again."""
    c = control or Control(connection() or {})
    if device:
        d = find_device(devices(c.hs("nodes", "list")), device)
        c.hs("nodes", "expire", "--identifier", str(d["id"]))
        return {"expired_device": d, "words": f"{d['name']} must sign in again (a server: join it again with a new code)."}
    pending = codes(c.hs("preauthkeys", "list"))
    for k in pending:
        c.hs("preauthkeys", "expire", "--id", str(k["id"]))
    return {"expired_codes": [k["id"] for k in pending],
            "words": f"{len(pending)} unused join code{'s' if len(pending) != 1 else ''} expired." if pending
                     else "No unused join codes: nothing to expire."}


def approve(code, user=None, control=None):
    state = (control.state if control else connection()) or {}
    c = control or Control(state)
    code = (code or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,128}", code):
        raise NetError("Give the code the device shows (bromigos lab network approve CODE)")
    owner = user or state.get("owner")
    n = c.hs("auth", "register", "--auth-id", code, "--user", owner)
    name = _g(n or {}, "given_name", "givenName", "name", default="the device")
    return {"approved": name, "user": owner, "words": f"{name} is on the lab network, as {owner}'s device."}


# ------------------------------------------------------------------ apply

def _health(o, t, tries=60):
    c = Control({"target": t})
    for _ in range(tries):
        try:
            c.hs("health", json_out=False)
            return True
        except (NetError, subprocess.TimeoutExpired):
            time.sleep(2)
    raise NetError("Headscale didn't answer after two minutes: look at its log (journalctl -u headscale on the "
                   "machine, or kubectl -n lab-network logs deploy/headscale)")


def apply(o, repo, p):
    repo = Path(repo)
    net = repo / "network"
    t = target_of(o)
    if o["on"] == "quadlet":
        base = ssh_args(t)
        run(base + ["sudo -n install -d -m 0750 /etc/headscale /etc/headscale/oidc"])
        for name, dest, mode in (("config.yaml", "/etc/headscale/config.yaml", "0640"),
                                 ("acl.hujson", "/etc/headscale/acl.hujson", "0640"),
                                 ("quadlet/headscale.container", "/etc/containers/systemd/headscale.container", "0644"),
                                 ("quadlet/headscale-data.volume", "/etc/containers/systemd/headscale-data.volume", "0644")):
            run(base + [f"sudo -n install -D -m {mode} /dev/stdin {shlex.quote(dest)}"], (net / name).read_text())
        if o["oidc"]:
            run(base + ["sudo -n install -m 0600 /dev/stdin /etc/headscale/oidc/client_secret"],
                Path(o["oidc_secret_file"]).expanduser().read_text().strip() + "\n")
        run(base + ["sudo -n systemctl daemon-reload && sudo -n systemctl restart headscale.service"])
    elif o["on"] == "k3s":
        if t["kind"] == "kubectl":
            kube = ["--kubeconfig", t["kubeconfig"], "--kube-context", t["context"]]
            if o["oidc"]:
                secret = json.dumps({"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "headscale-oidc", "namespace": NAMESPACE},
                                     "type": "Opaque", "stringData": {"client_secret": Path(o["oidc_secret_file"]).expanduser().read_text().strip()}})
                run(["kubectl", "--kubeconfig", t["kubeconfig"], "--context", t["context"], "create", "namespace", NAMESPACE], check=False)
                run(["kubectl", "--kubeconfig", t["kubeconfig"], "--context", t["context"], "apply", "-f", "-"], secret)
            run(["helm", "upgrade", "--install", "headscale", str(net / "helm/headscale"), "-n", NAMESPACE,
                 "--create-namespace", "--wait", "--timeout", "5m"] + kube, timeout=400)
        else:
            base = ssh_args(t)
            import tarfile, io
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:gz") as tar:
                tar.add(net / "helm/headscale", arcname="headscale")
            import base64
            payload = base64.b64encode(buf.getvalue()).decode()
            remote = ("set -e; d=$(mktemp -d); trap 'rm -rf \"$d\"' EXIT; base64 -d | tar -xz -C \"$d\"; "
                      f"sudo -n helm upgrade --install headscale \"$d/headscale\" -n {NAMESPACE} --create-namespace "
                      "--wait --timeout 5m --kubeconfig /etc/rancher/k3s/k3s.yaml")
            if o["oidc"]:
                secret = json.dumps({"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "headscale-oidc", "namespace": NAMESPACE},
                                     "type": "Opaque", "stringData": {"client_secret": Path(o["oidc_secret_file"]).expanduser().read_text().strip()}})
                run(base + [f"sudo -n k3s kubectl create namespace {NAMESPACE} 2>/dev/null || true; sudo -n k3s kubectl apply -f -"], secret)
            run(base + [remote], payload, timeout=400)
    else:
        e = o["engine"]
        if run([e, "network", "inspect", o["docker_network"]], check=False).returncode:
            run([e, "network", "create", o["docker_network"]])
        run([e, "rm", "-f", o["container"]], check=False)
        f = container_flags(o)
        argv = [e, "run", "-d", "--name", o["container"], "--network", o["docker_network"],
                "-v", f"{net}:/etc/headscale:ro", "-v", f"{o['container']}-data:/var/lib/headscale"]
        argv += ["--read-only"] if f["read_only"] else []
        argv += [x for t_ in f["tmpfs"] for x in ("--tmpfs", t_)]
        argv += ["--security-opt", "no-new-privileges"] if f["no_new_privileges"] else []
        run(argv + [o["image"], "serve"])
    _health(o, t)
    control = Control({"target": t})
    if not o["oidc"]:
        users = control.hs("users", "list") or []
        if not any(u.get("name") == o["owner"] for u in users):
            control.hs("users", "create", o["owner"])
    if o["endpoint"] in ("relay", "router"):
        try:
            urllib.request.urlopen(o["server_url"] + "/health", timeout=20).read()
        except (urllib.error.URLError, OSError) as e:
            say(f"Note: {o['server_url']} doesn't answer from here yet ({getattr(e, 'reason', e)}). Check the domain "
                "points at the " + ("relay" if o["endpoint"] == "relay" else "router") + " and the port is open; "
                "Headscale gets its certificate on the first visit.")
    save_connection(o["server_url"], o["name"], net / "network.json")


# ------------------------------------------------------------------ the QR code

def qr_lines(text):
    """The join bundle as a QR code in a terminal: the shared themed component (bromigos_qr) when
    it's installed, else plain half blocks. Empty when neither can draw one."""
    try:
        import bromigos_qr
        return list(bromigos_qr.terminal(text))
    except Exception:
        pass
    try:
        import qrcode
    except ImportError:
        return []
    q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=2)
    q.add_data(text)
    q.make(fit=True)
    m = q.get_matrix()
    if len(m) % 2:
        m.append([False] * len(m[0]))
    chars = {(False, False): "█", (True, False): "▄", (False, True): "▀", (True, True): " "}
    return ["".join(chars[(m[y][x], m[y + 1][x])] for x in range(len(m[0]))) for y in range(0, len(m), 2)]


# ------------------------------------------------------------------ the command line

def _print_status(doc, a):
    if a.json:
        say(json.dumps(doc, indent=1))
        return 0
    if not doc["configured"]:
        say(doc["words"])
        return 0
    say(f"{doc['name']} · {doc['login_server']} · {doc['summary']}")
    for d in doc["devices"]:
        mark = "●" if d["online"] else "○"
        what = {"lab": "lab machine", "server": "server", "device": f"{d['user']}'s device"}[d["kind"]]
        say(f"  {mark} {d['name']:<24} {what:<20} {', '.join(d['ips'][:1]):<16} "
            f"{'online' if d['online'] else 'seen ' + ago(d['seen_ago']) if d['seen_ago'] is not None else 'never seen'}"
            + ("  (key expired: sign in again)" if d["expired"] else ""))
    for k in doc["codes"]:
        say(f"  · join code {k['id']} for {', '.join(t.removeprefix('tag:') for t in k['tags']) or 'a device'}, until {k['expires'][:16]}")
    return 0


def _confirm(prompt, expected, a):
    if getattr(a, "yes", False):
        return True
    if not sys.stdin.isatty():
        raise NetError("Run it in a terminal to confirm, or pass --yes")
    return input(prompt).strip() == expected


def main(argv=None):
    p = argparse.ArgumentParser(prog="bromigos lab network", description="Your lab's own private network (Headscale)")
    sub = p.add_subparsers(dest="verb")
    s = sub.add_parser("setup", help="plan Headscale in your lab, review it, then apply after yes")
    s.add_argument("--on", choices=("k3s", "quadlet", "dev"))
    s.add_argument("--node", help="the lab machine as user@host (the Quadlet's machine, or a k3s box over SSH)")
    s.add_argument("--port", type=int)
    s.add_argument("--identity")
    s.add_argument("--known-hosts")
    s.add_argument("--kubeconfig")
    s.add_argument("--context")
    s.add_argument("--endpoint", choices=tuple(ENDPOINTS))
    s.add_argument("--domain", help="the network's address on the internet, such as net.example.org")
    s.add_argument("--email", help="for Let's Encrypt's notices about the certificate")
    s.add_argument("--lan-address", help="--endpoint lan: the lab machine's address on your network")
    s.add_argument("--public-port", type=int, help="k3s with --endpoint router: the node port your router forwards 443 to")
    s.add_argument("--derp", choices=("tailscale", "embedded", "self"))
    s.add_argument("--owner", help="the network's owner: a user name, or your email with an identity provider")
    s.add_argument("--oidc-issuer")
    s.add_argument("--oidc-client-id")
    s.add_argument("--oidc-secret-file")
    s.add_argument("--oidc-allowed-domains", nargs="+")
    s.add_argument("--name", help="what to call the network")
    s.add_argument("--dns-domain", help=f"the devices' names end in this (default {DNS_DOMAIN})")
    s.add_argument("--engine", choices=("docker", "podman"), help="--on dev")
    s.add_argument("--container", help="--on dev")
    s.add_argument("--docker-network", help="--on dev")
    s.add_argument("--server-url", help="--on dev: the address the dev clients use")
    s.add_argument("--image", help=argparse.SUPPRESS)
    s.add_argument("--repo", help="your lab repository (default: the provisioned lab's)")
    s.add_argument("--plan-only", action="store_true", help="write and show the plan; don't apply")
    s.add_argument("--brief", action="store_true", help="list the files without printing them")
    s.add_argument("--yes", action="store_true", help="apply without asking (the plan is still shown)")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("join", help="a one-time join code for a machine, as a bundle and a QR code")
    s.add_argument("--tag", choices=tuple(TAGS), default="server")
    s.add_argument("--expires", default="24h")
    s.add_argument("--reusable", action="store_true")
    s.add_argument("--ephemeral", action="store_true", help="the machine leaves the network when it goes offline")
    s.add_argument("--stick", action="store_true", help="also keep it in homelab.toml, so the next Field Kit stick carries it")
    s.add_argument("--no-qr", action="store_true")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("connect", help="join THIS machine with a join bundle")
    s.add_argument("bundle", nargs="?", help="the bundle, or - to read it; default: one this machine was given")
    s.add_argument("--hostname")
    s.add_argument("--force", action="store_true", help="leave the network this machine is on now")
    s.add_argument("--json", action="store_true")
    sub.add_parser("reach", help="Reach it from anywhere: the four choices for this machine")
    s = sub.add_parser("status", help="devices: online, last seen, tags")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("approve", help="a device showing a code after signing in")
    s.add_argument("code")
    s.add_argument("--user")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("remove", help="take a device off the network")
    s.add_argument("device")
    s.add_argument("--yes", action="store_true")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("rotate", help="expire unused join codes, or make a device sign in again")
    s.add_argument("--device")
    s.add_argument("--yes", action="store_true")
    s.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    if not a.verb:
        a = p.parse_args(["status"] + list(argv or []))
    try:
        if a.verb == "setup":
            repo = a.repo or default_repo()
            saved = None
            existing = Path(repo).expanduser() / "network" / "network.json"
            if existing.exists():
                saved = json.loads(existing.read_text())
                saved.pop("target", None), saved.pop("version", None), saved.pop("oidc_secret_file", None)
            o = options(a, saved)
            pl = plan(o, repo)
            repo_path, changed = write_files(repo, pl["files"])
            if a.json and (a.plan_only or not a.yes):
                say(json.dumps({"server_url": pl["server_url"], "files": sorted(pl["files"]), "changed": changed,
                                "steps": [{"words": w, "command": c} for w, c in pl["steps"]], "ports": pl["ports"],
                                "notes": pl["notes"], "repo": str(repo_path), "applied": False}, indent=1))
                return 0
            if not a.json:
                review(pl, o, repo_path, changed=changed, full=not a.brief)
            if a.plan_only:
                say("Plan kept. Nothing applied. Review and commit the files, then run setup again to apply.")
                return 0
            if not a.yes and (not sys.stdin.isatty() or input("Apply this plan? Type yes: ").strip() != "yes"):
                say("Plan kept. Nothing applied.")
                return 0
            apply(o, repo_path, pl)
            if a.json:
                say(json.dumps({"server_url": pl["server_url"], "repo": str(repo_path), "applied": True}))
            else:
                say(f"Your lab's network is up at {pl['server_url']}. Add a machine: bromigos lab network join")
            return 0
        if a.verb == "status":
            return _print_status(status(), a)
        if a.verb == "join":
            doc = join(a.tag, a.expires, a.reusable, a.ephemeral)
            if a.stick:
                state = connection()
                save_connection(state["server_url"], state.get("name") or "", state["plan_path"], doc["bundle"])
                doc["stick"] = True
            if a.json:
                say(json.dumps(doc, indent=1))
                return 0
            say(f"A join code for a {a.tag} machine, good once" + (" (reusable)" if a.reusable else "")
                + f", until {doc['expires'][:16].replace('T', ' ')} UTC.")
            lines = [] if a.no_qr else qr_lines(doc["bundle"])
            if lines:
                say("\n".join(lines))
            say("\nThe join code (the installer, Field Kit and bromigOS Server take it pasted):\n" + doc["bundle"])
            say("\nOr on any Linux machine with Tailscale's app:\n  " + doc["command"])
            if a.stick:
                say("\nKept in homelab.toml: the next Field Kit stick you make carries it (bromigos fieldkit make-stick).")
            return 0
        if a.verb == "connect":
            text = sys.stdin.read() if a.bundle == "-" else a.bundle
            if not text:
                found = R.find_bundles()
                if found:
                    where, text = found[0]
                    if not a.json:
                        say(f"Using the join code {where}: {R.describe(R.decode(text))}")
                elif sys.stdin.isatty() and not a.json:
                    say("Join this machine to your lab's private network. Make a join code in your lab "
                        "(bromigos lab network join, or the lab console's NETWORK tab), then paste it here.")
                    text = input("Join code: ").strip()
                else:
                    raise NetError("No join code on this machine. In your lab: bromigos lab network join, then "
                                   "bromigos lab network connect CODE")
            result = R.join_now(text, a.hostname, force=a.force)
            say(json.dumps(result) if a.json else result["words"])
            return 0 if result["ok"] else 1
        if a.verb == "reach":
            answer = R.choose()
            result = R.apply(answer)
            say(result["words"])
            return 0 if result.get("ok", True) else 1
        if a.verb == "approve":
            doc = approve(a.code, a.user)
            say(json.dumps(doc) if a.json else doc["words"])
            return 0
        if a.verb == "remove":
            state = connection()
            if not state:
                raise NetError("No lab network yet: bromigos lab network setup")
            c = Control(state)
            d = find_device(devices(c.hs("nodes", "list")), a.device)
            if not _confirm(f"Take {d['name']} off the lab network? Type its name to confirm: ", d["name"], a):
                say("Kept. Nothing removed.")
                return 0
            doc = remove(str(d["id"]), control=c)
            say(json.dumps(doc) if a.json else doc["words"])
            return 0
        if a.verb == "rotate":
            if not a.device and not a.yes and sys.stdin.isatty() and \
                    input("Expire every unused join code? Type yes: ").strip() != "yes":
                say("Kept. Nothing expired.")
                return 0
            doc = rotate(a.device)
            say(json.dumps(doc) if a.json else doc["words"])
            return 0
    except (NetError, R.BundleError) as e:
        if getattr(a, "json", False):
            say(json.dumps({"ok": False, "error": str(e)}))
        else:
            print("Lab network: " + str(e), file=sys.stderr)
        return 1
    except (OSError, subprocess.TimeoutExpired) as e:
        print("Lab network: " + (str(e) if isinstance(e, OSError) else "a command took too long"), file=sys.stderr)
        return 1
    return 2
