# The Bromigos account sign-in

bromigOS can sign in to a person's Bromigos account. The account is optional, and nothing
on the desktop needs it. This page explains how the sign-in works, where its parts live,
and how other bromigOS code uses it. The manual's
[Your Bromigos account](../manual/src/bromigos-account.md) page is the user's guide.

> **Not live yet.** The account service at auth.bromigos.org and account.bromigos.org is
> being built. bromigOS is built against the contract below, and tested against a stand-in
> server. The first sign-ins against the real service are still to be checked.

## The parts

| File | What it does |
|---|---|
| `lib/bromigos_account.py` | The sign-in helper every account uses. Bromigos is its provider `bromigos`: the device flow, the keyring item, refresh and personal access tokens |
| `lib/bromigos_login.py` | What only the Bromigos account has: the SSH sign-in, the account's SSH keys, and the `login`, `logout` and `whoami` commands |
| `bin/bromigos-login`, `bin/bromigos-logout`, `bin/bromigos-whoami` | The commands `bromigos login`, `logout` and `whoami`, in `bromigos-core` |
| `homelab/lib/bromigos_homelab/accountkeys.py` | Adds the account's SSH keys to a new lab box ([lab-provision.md](lab-provision.md#your-accounts-ssh-keys)) |
| `desktop/settings/pages/account.py` | The **Bromigos account** row in Settings › Account ([settings.md](settings.md#account)) |

## The service it talks to

The sign-in server is an OpenID Connect issuer, `https://auth.bromigos.org`. bromigOS reads
its endpoints from the discovery document, `<issuer>/.well-known/openid-configuration`.
When that can't be read, it falls back to `<issuer>/oauth2/device/auth`,
`<issuer>/oauth2/token`, `<issuer>/userinfo` and `<issuer>/oauth2/revoke`.

| What | Value |
|---|---|
| Client | `bromigos-cli`, a public client with no secret |
| Flow | The device authorization grant (RFC 8628) |
| Scopes | `openid offline_access profile email`, plus the service scopes listed in `PROVIDERS["bromigos"]` |
| Where the code is entered | `https://account.bromigos.org/device`, the `verification_uri` the server returns |
| Refresh tokens | They rotate: each refresh returns a new one, and the old one stops working |

The account website, `https://account.bromigos.org`, has the API for SSH:

| Request | Answer |
|---|---|
| `GET /api/me/ssh-keys` with `Authorization: Bearer <token>` | `[{"fingerprint", "type", "public_key", "title", "created_at", "last_used_at"}]` |
| `POST /api/ssh/nonce` with `{"user_code"}` | `{"nonce", "expires_in"}` |
| `POST /api/ssh/approve` with `{"user_code", "nonce", "signature"}` | Success approves the device code |

## Signing in

`bromigos login` runs the device flow. It prints the page and the code, then polls the
token endpoint, honouring `slow_down`. In a desktop session it offers to open the page.
Pressing Enter runs `xdg-open` on `verification_uri_complete`, which has the code filled
in. Polling carries on meanwhile, so approving from a phone works too. It never offers a
browser when `SSH_CONNECTION`, `SSH_CLIENT` or `SSH_TTY` is set, when there's no
`WAYLAND_DISPLAY` or `DISPLAY`, when stdin isn't a terminal, or with `--no-browser`.

### With an SSH key

`bromigos login --ssh` signs in without a browser:

1. It starts the device flow, which gives a user code.
2. It asks `POST /api/ssh/nonce` for a nonce for that code.
3. It signs `bromigos-login\n<user_code>\n<nonce>` with
   `ssh-keygen -Y sign -n bromigos-login`. A key in ssh-agent signs there, with
   `-f <public key> -U`. Otherwise `-f` names the private key file.
4. It sends the signature to `POST /api/ssh/approve`.
5. It polls the token endpoint, as the device flow always does.

The message goes to ssh-keygen in a file, not on stdin. So a passphrase is read from the
terminal, and no password window opens. FIDO keys, such as `sk-ssh-ed25519`, work the same
way and ask for a touch.

Keys come from `ssh-add -L` and from `~/.ssh/*.pub` files that have a private key beside
them. A key in both is used through the agent. With several keys, it asks which one.
`--key PATH` takes a private key or its `.pub`. A 403 or 404 from approve, or an error
naming the key, means the account doesn't have that key. The command then prints the
public key and says to add it at account.bromigos.org › SSH keys.

### With a personal access token

Personal access tokens start with `bmg_pat_`. People make them on the website, and
`bromigos account token` prints the steps. `bromigos login --with-token` reads one from
stdin, or asks for it without echoing on a terminal. It refuses anything without the
prefix, or with spaces in it. While `BROMIGOS_TOKEN` is set, it stands in for the stored
sign-in, the way `gh`'s login does for GitHub.

## Where the sign-in is kept

The tokens are one item in the login keyring, through libsecret: service
`bromigos-account:bromigos`, account `default`, labelled "bromigOS: Bromigos sign-in". The
item holds the access and refresh tokens, their expiry, the user name and email from
userinfo, and how the sign-in was made: `device`, `ssh` (with the key's fingerprint) or
`token`. No token is ever written to a file or printed.

`bromigos logout` sends the refresh token to the revocation endpoint, then deletes the
item. It doesn't wait for the service, and it never revokes a pasted token.

## Using it from bromigOS code

```python
import bromigos_account as A
import bromigos_login as L

tok = L.token()                       # a valid access token, or None when signed out
keys = L.account_ssh_keys()           # the account's SSH keys, checked; None when signed out
doc = A.authed_json("bromigos", L.site() + "/api/me/ssh-keys")
```

`A.token("bromigos")` refreshes an access token within a minute of its expiry.
`A.authed_json` adds the bearer token. After a 401 it refreshes once and tries again, and
raises `SignInError` when the sign-in can't be renewed.

Refresh tokens rotate, so two programs mustn't refresh at once. The second would send a
token that's already been used, and the service may then end the whole sign-in. A refresh
takes a lock, `$XDG_RUNTIME_DIR/bromigos/account-<provider>-<account>.lock`, and reads the
keyring again under it. If another program has refreshed meanwhile, it uses that token.

`account_ssh_keys()` checks every key before anything uses it. The key type must be one
OpenSSH knows, the line must have no options and no line breaks, and the blob must decode
and name the same type. The fingerprint is worked out locally, not taken from the answer.
Each key's `line` is ready for an authorized_keys file, with its title as the comment.

## Settings for a test server

The environment wins over `accounts.toml`, and `accounts.toml` wins over the defaults.

| Environment | `[bromigos]` in `accounts.toml` | Default |
|---|---|---|
| `BROMIGOS_ACCOUNT_URL` | `base` | `https://account.bromigos.org` |
| `BROMIGOS_AUTH_URL` | `issuer` | `https://auth.bromigos.org` |
| `BROMIGOS_CLIENT_ID` | `client_id` | `bromigos-cli` |
| `BROMIGOS_SCOPES` | `scopes` | The scopes in `PROVIDERS["bromigos"]` |

Scopes take spaces or commas between them.

## Tests

`tests/account/test_bromigos_login.py` signs in against `tests/account/mockaccount.py`, a
stand-in service on 127.0.0.1. It has discovery, the device flow, a token endpoint that
rotates refresh tokens and spots a reused one, userinfo, revocation and the SSH API. The
SSH approval checks each signature with `ssh-keygen -Y verify`, against the account's keys.

The tests make throwaway keys with ssh-keygen in a temporary home. One starts its own
ssh-agent on a socket in a temporary folder. The keyring is `MemoryKeyring`, and the
browser is a stand-in, so no window opens. They cover the device flow, the browser offer,
key files, agent keys, a key the account doesn't have, choosing among keys, personal
access tokens, `BROMIGOS_TOKEN`, refresh under the lock, a 401 and logout.

```bash
PYTHONPATH=lib python -m unittest discover -s tests/account
```

`bromigos-core`'s `check()` runs them. `homelab/tests/test_provision_accountkeys.py` covers
the lab side ([lab-provision.md](lab-provision.md#your-accounts-ssh-keys)).
