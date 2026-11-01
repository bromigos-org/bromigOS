# The secret store: bromigos lab secrets

Every key a server needs goes into one store, chosen at install: the VPN login, the Usenet
provider's, Plex's claim code, Pelican's and Wings' tokens, the lab network's join keys, the
backup password, VECTOR's and LiteLLM's provider keys, game servers' admin passwords and the
media apps' API keys. People never manage them by hand
([the manual](../manual/src/lab.md#where-your-keys-live) has the plain version).

- **Typed keys** are saved the moment they're entered.
- **Generated keys** (database passwords, API keys, the backup password, tokens between
  services) are made once, random (`secrets.token_urlsafe(32)`, API keys
  `token_hex(16)`), and different for every app. There are no default passwords.
- **Nothing secret** goes into a config file, the answer file, a log or the journal, or Git
  unless sops encrypts it. `bromigos lab secrets scan ROOT --also FILE` checks a tree.

## The module

`bromigos_homelab.secretstore`. `bromigos lab secrets` is its command; on bromigOS Server,
`bromigos server secrets` is the same command.

```python
from bromigos_homelab import secretstore as S
S.choices(lab="new", vault_selected=True)   # the installer's answers to "Where should this server keep its keys?"
store = S.open_store()                      # from /etc/bromigos/secrets.toml (no values in it)
store.put("gluetun/password", value)        # typed
store.generate("sonarr/api-key", "apikey", users=["sonarr.service"])
store.get(name); store.exists(name); store.names(); store.delete(name)
store.rotate(name[, value])                 # restarts the units in users
store.summary()                             # "N keys stored …", never values
store.recovery_text()                       # where they live and how to get them back
S.write_config({"backend": "vault", "vault": {"address": "https://vault.example.org", "auth": "approle"}})
S.resolve_ref({"secret": "vault:kv/path#field"}, store)
S.external_secret_manifests(address, mount, prefix, app, keys)
S.scan(root, values, extra_files)
```

Names are `ITEM/FIELD`. A key's Podman secret is `bromigos-ITEM-FIELD`; its systemd
credential is `bromigos.ITEM.FIELD`.

## Backends

| backend | Where | How services read them |
|---|---|---|
| `local` | `/etc/credstore.encrypted/`, `systemd-creds encrypt --with-key=auto` (the TPM2 chip plus the host key when there's a TPM, the host key alone when not; never TPM-only, so the recovery bundle still works after a board swap) | host units: `LoadCredentialEncrypted=`; containers: Podman's shell secret driver (`/etc/containers/containers.conf.d/50-bromigos-secrets.conf`), which stores and looks up with `systemd-creds`, mounted as files |
| `vault` | an existing HashiCorp Vault or OpenBao, KV v2, under `kv/bromigos/servers/<hostname>/` (or `secret/lab/servers/<hostname>/` when the lab's Vault has the layout `bromigos lab provision` makes) | the same: the store keeps encrypted local copies for host units and Podman |
| `openbao` | a new OpenBao on this server, for a new lab with the Vault item | as `vault` |
| `sops` | the lab repository's `secrets.enc.json`, sops and age | as `bromigos lab provision` |

**Signing in to a Vault.** AppRole (a role id and secret id), a one-time wrapped token
(`sys/wrapping/unwrap`; it may wrap a token or an AppRole secret id), or OIDC
(`oidc_auth_url()` then `oidc_callback()`). A root token is refused. No long-lived token is
kept: the AppRole's ids are kept as local credentials, and each run signs in for an hour.
`ensure_server_policy(hostname)` (with an admin token, once) makes the server's policy,
`bromigos-server-<hostname>`, which reads and writes its own path and nothing else, and its
AppRole. `policy_preview()` shows the policy first; `test()` checks the connection, the seal
and the path.

**A new OpenBao.** `OpenBaoStore.initialise()` at first boot: five unseal shares, threshold
three; unseal; the file audit device on (`/var/log/openbao/audit.log`); a KV v2 store at `kv/`;
the server's policy and AppRole; the root token revoked. `take_init_keys()` hands the shares to
the welcome tour once (it shows them with a QR code). Three shares are kept as TPM-bound
local credentials so `bromigos-openbao-unseal.service` unseals it after a restart; keep all
five safe anyway.

**The recovery bundle** (local). `recovery_key()` makes an age key once and returns it to show;
`/var/lib/bromigos/secrets/recovery.age` holds every key encrypted to it, rewritten on every
change. `ack_recovery()` forgets the key on the server once it's saved;
`restore(bundle, key)` puts every key back.

**Kubernetes labs.** Secrets reach apps through the External Secrets Operator (the
`external-secrets` catalogue item) and a `ClusterSecretStore` for the lab's Vault;
`external_secret_manifests()` writes those references for the lab repository.

**Password managers.** `import_bitwarden(store, {name: "item#field"})` fills keys through
`bitwarden-cli` (`bw`, with `BW_SESSION` from `bw unlock`); it works with Vaultwarden. The
readers are one function each, so others can be added.

## Rotation

`bromigos lab secrets rotate NAME`: a new random value (a typed key asks for the new one),
saved, the Podman copy replaced, and every unit recorded as using it restarted (a replaced
Podman secret doesn't reach a running container). The lab console can call
`store.rotate(name)` the same way.

## Tests

`homelab/tests/test_secretstore.py`: the local store with a TPM stand-in and without; Vault
and OpenBao against an HTTP stub of Vault's API on 127.0.0.1 (`tests/provfake.py`: KV v2,
AppRole, wrapping, policies with path matching, mounts, audit, init and unseal), because
rootless Podman isn't available to the test run for a real dev server; sops; references; the
scanner. `test_local_provision.py` checks that rendered units name secrets and that no value
lands under the target root or in the answer file.
