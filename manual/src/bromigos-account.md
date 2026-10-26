# Your Bromigos account

A Bromigos account is your sign-in for Bromigos services. On bromigOS it's optional.
Everything on the desktop works without one. Sign in when you want bromigOS to use your
account, for example to put the SSH keys on your account on a new lab box.

You make and manage the account on the website, account.bromigos.org. bromigOS keeps the
sign-in in your [keyring](#your-keyring), the same place it keeps your other passwords.
It's never written to a file.

## Sign in

```bash
bromigos login
```

It shows a web address and a short code:

```text
To sign in to your Bromigos account, open this page on any device:
    https://account.bromigos.org/device
and enter this code:
    WDJB-MJHT
The code works for 15 minutes.
Press Enter to open it in your browser, or approve it from another device. Waiting… (Ctrl+C stops)
```

Open the page on this computer or on your phone, sign in there, and enter the code. The
terminal says who you're signed in as once you approve it.

On your desktop, pressing Enter opens the page in your browser with the code filled in.
Over SSH, or with `--no-browser`, bromigOS only prints the address and the code, and
never opens a browser.

You can also sign in from Settings. Open Settings › Account, and choose **Sign in…** under
**Bromigos account**. It runs the same sign-in in a terminal.

## Sign in with an SSH key

If your account has your SSH public key, you can sign in with that key instead of a
browser. This suits a computer you reach over SSH, or one with no browser.

```bash
bromigos login --ssh
```

bromigOS looks for keys in ssh-agent and in `~/.ssh`. If it finds more than one, it asks
which to use. To choose one yourself, name it:

```bash
bromigos login --ssh --key ~/.ssh/id_ed25519
```

The key signs a one-time challenge from the website, so the key itself never leaves your
computer. A key in ssh-agent signs there. A key file with a passphrase asks for it, and a
security key, such as a YubiKey, asks for a touch.

If your account doesn't have that key, bromigOS says so and prints its public key. Add it
on the website, at account.bromigos.org › SSH keys, then run `bromigos login --ssh` again.

## Use a personal access token

A personal access token lets a script or another computer use your account without
signing in. Tokens start with `bmg_pat_`. You make them on the website. bromigOS can't
make one for you. To see the steps, run:

```bash
bromigos account token
```

To store a token on this computer, run this and paste the token when it asks:

```bash
bromigos login --with-token
```

Or pipe it in, as in `bromigos login --with-token < token.txt`. bromigOS keeps the token
in your keyring and never prints it.

For one script, or a computer without a keyring, set `BROMIGOS_TOKEN` instead. While it's
set, bromigOS uses it in place of a stored sign-in.

Treat a token like a password. Delete it on the website when you no longer need it.

## See who's signed in

```bash
bromigos whoami
```

It says which account this computer is signed in to, and how: with a code on the website,
an SSH key or a token. Settings › Account shows the same.

## Sign out

```bash
bromigos logout
```

This computer forgets the sign-in, and tells the website to end it. Your account, its SSH
keys and its tokens stay as they are. If `BROMIGOS_TOKEN` is set, unset it too.

## Staying signed in

A sign-in lasts until you sign out. bromigOS renews it in the background when it's used, so
you don't sign in again each day. If you end the sign-in on the website, the next thing
that uses your account says so. Run `bromigos login` again.

## Your keyring

Your keyring is where bromigOS keeps sign-ins and passwords. It's encrypted with your login
password. bromigOS's keyring is oo7. It starts with your session, and your login password
unlocks it, so nothing asks you for a password. Other apps that keep passwords in a
keyring use the same one, such as web browsers and Git.

To check it, run:

```bash
bromigos keyring status
```

It says whether the keyring is running and unlocked, and whether your login unlocks it.
When something needs fixing, it says what to run.

### Let your login unlock it

`bromigos keyring setup` makes your login unlock the keyring. `bromigos update` runs it
once for you, and asks for your password through sudo. It adds oo7's lines to these login
settings in `/etc/pam.d`:

- `login`, the [text console login](console-login.md);
- `sddm`, the login screen;
- `passwd`, so a new password carries over to the keyring.

Lines that are already there stay as they are. The setup also turns off KWallet's own
keyring service, so it can't take oo7's place. KWallet itself keeps working.

Sign out and in again afterwards. From then on, your login unlocks the keyring.

### If sign-in says there's no keyring

`bromigos login` checks the keyring before it shows a code, so you never approve a
sign-in that can't be kept. If it says **No keyring is running**, install oo7 from
bromigOS's repository, set it up, then sign out and in again:

```bash
sudo pacman -S bromigos/oo7
bromigos keyring setup
```

`bromigos update` installs oo7 too, because the desktop needs it.

If you used gnome-keyring before, pacman asks whether to remove it. Answer **y**, because
oo7 takes its place. The next time you sign in, oo7 moves your saved passwords over.

If it says **Your keyring is locked**, the keyring is waiting for its password and there's
no desktop here to ask for it. This happens when you sign in some other way, such as over
SSH. On your desktop, apps show a password window instead. Type your login password there.

## What uses your account

- [Setting up a lab](lab.md#your-accounts-ssh-keys-on-the-box) offers to put the SSH keys
  on your account on the new box.

## Use another account server

For testing, bromigOS can sign in to another server. Set these in the environment, or in
`~/.config/bromigos/accounts.toml` under `[bromigos]` without the `BROMIGOS_` prefix, in
lower case:

| Setting | What it is |
|---|---|
| `BROMIGOS_ACCOUNT_URL` (`base`) | The account website. The default is `https://account.bromigos.org` |
| `BROMIGOS_AUTH_URL` (`issuer`) | The sign-in server. The default is `https://auth.bromigos.org` |
| `BROMIGOS_CLIENT_ID` (`client_id`) | The app bromigOS signs in as. The default is `bromigos-cli` |
| `BROMIGOS_SCOPES` (`scopes`) | What the sign-in asks to do, with spaces between |
