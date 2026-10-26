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
| `lib/bromigos_keyring.py`, `bin/bromigos-keyring` | The keyring the sign-in is kept in: its check, its errors in plain words, and `bromigos keyring status` and `setup` ([below](#the-keyring)) |
| `migrations/20261026120000-keyring-unlock.sh` | Runs `bromigos keyring setup` once per user, on update |
| `packaging/oo7/` | bromigOS's build of oo7, the keyring ([packaging/README.md](../packaging/README.md#the-packages)) |
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

## The keyring

The sign-in is only as good as the keyring that keeps it. bromigOS's keyring is oo7, the
`oo7` package: `oo7-daemon` answers to the Secret Service's D-Bus name,
`org.freedesktop.secrets`, and `pam_oo7.so` hands it the login password.

- **It starts with the session.** `bromigos-desktop` depends on `oo7>=0.7.0beta`, `gcr` and
  `libsecret`. It ships a `default.target.wants` link for `oo7-daemon.service`. oo7's login
  helper holds the password for up to two minutes, until the daemon takes it, so the daemon
  must start with the session, not on first use.
- **The login unlocks it.** `bromigos keyring setup` adds these lines, after the last line
  of the same kind, to `/etc/pam.d/login`, `/etc/pam.d/sddm` and `/etc/pam.d/passwd`:

  ```text
  -auth      optional     pam_oo7.so
  -session   optional     pam_oo7.so auto_start
  -password  optional     pam_oo7.so
  ```

  `login` and `sddm` get the first two, and `passwd` the third. The `-` makes PAM skip a
  line whose module isn't installed, and `optional` means it never decides whether someone
  gets in. A file that already runs `pam_oo7.so` for that kind, written any way, is left
  alone. Other lines, such as a hand-added `pam_gnome_keyring.so`, are never touched.
- **It writes safely.** The edit runs as root through sudo
  (`bromigos keyring pam`). It checks that the new text is the old text plus its own lines
  and nothing else, then writes a file beside the old one with the same owner and mode and
  renames it over. A file it can't place a line in, one with no line of that kind, is
  reported and left as it is.
- **One keyring answers.** KWallet ships its own Secret Service, `ksecretd`, which takes the
  name when it starts first, for example from `pam_kwallet5.so` at the login screen. Then
  oo7 can't start. `setup` sets `apiEnabled=false` under `[org.freedesktop.secrets]` in
  `~/.config/kwalletrc`. KWallet's own interface, which KDE apps use, keeps working.
- **The update runs it.** `migrations/20261026120000-keyring-unlock.sh` runs
  `bromigos keyring setup` once per user. It asks for sudo on the terminal. Without a
  terminal, as in the ISO's installer, it uses sudo only when sudo needs no password.
  When sudo doesn't run, or oo7 isn't installed yet, it exits 75, and the next update
  tries again.
- **gnome-keyring makes way.** oo7 conflicts with gnome-keyring. pacman asks to remove it,
  and its answer defaults to no. So `bromigos update` says beforehand to answer y. With
  `--yes`, it says to run the update without it. oo7 moves gnome-keyring's
  `~/.local/share/keyrings/*.keyring` into its own keyring the first time the login
  password unlocks it.

### Checks before a sign-in

`bromigos_keyring.ready()` asks the session bus, through `busctl --user`, whether
`org.freedesktop.secrets` is running or can start, and whether the default keyring is
locked. It never starts the service to find out. `bromigos login` and
`bromigos_account.sign_in()` ask it before the device flow starts, so a person never
approves a sign-in this computer can't keep. A sign-in is refused up front when:

- libsecret isn't installed;
- there's no session bus;
- no keyring runs and none can start;
- the keyring is locked, or not started yet, and no window can ask for its password.
  oo7 shows that window, through gcr's prompter, only to an app in a graphical session.
  So a terminal over SSH, or one with no desktop in its session's environment, can't
  unlock it.

A stand-in keyring, as the tests use, is always ready.

### Errors in plain words

libsecret raises a GLib error, whose text is a D-Bus error name, such as
`g-dbus-error-quark: The name is not activatable (2)`. `_SecretService` turns every
keyring error into `KeyringError`, a `RuntimeError`, worded by
`bromigos_keyring.explain()`. Storing gives up after two minutes, so a password window
nobody can see never hangs a sign-in. If storing fails after the person approved,
`bromigos login` says the sign-in wasn't kept, why, and what to do. A raw GLib error is
never printed.

### `bromigos keyring`

| Command | What it does |
|---|---|
| `bromigos keyring status [--json]` | Which keyring runs, locked or not, each PAM file's lines and KWallet's setting. Each problem comes with its fix. It exits 1 when something needs fixing |
| `bromigos keyring setup [--dry-run]` | The PAM lines, through sudo, and KWallet's Secret Service off. It exits 75 when it can't finish yet |

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

The account tests also cover the keyring's side of a sign-in: no keyring stops it before
the code is shown, and a store that fails after approval is reported in plain words.
`tests/keyring/test_keyring.py` tests the keyring module on copies. PAM files are edited in
a temporary root, with Arch's own files and a hand-edited one. `kwalletrc` sits in a
temporary home, and the session bus is a stand-in. Nothing reads or changes the machine's
`/etc`, starts a keyring or runs sudo.

```bash
PYTHONPATH=lib python -m unittest discover -s tests/keyring
```

`bromigos-core`'s `check()` runs them. `homelab/tests/test_provision_accountkeys.py` covers
the lab side ([lab-provision.md](lab-provision.md#your-accounts-ssh-keys)).
