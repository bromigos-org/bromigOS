"""The SSH keys on your Bromigos account, added to a new lab box's authorized_keys.

When this computer is signed in to a Bromigos account (`bromigos login`), `bromigos lab
provision` offers to add the account's SSH public keys to the box, for the user it
provisions through. The keys come from the account with the sign-in's token
(lib/bromigos_login.py, account_ssh_keys). Each is checked there: a known key type, no
options and no line breaks.

On the box, a short POSIX shell script appends only the keys that aren't there yet. It
never removes or rewrites a line. It makes ~/.ssh (mode 0700) and authorized_keys (mode
0600) only when they're missing, and leaves the modes of existing ones alone.

Without lib/bromigos_login.py (the standalone lab package on its own), or when signed
out, nothing is offered."""
import shlex

SCRIPT = r"""umask 077
d="$HOME/.ssh"
f="$d/authorized_keys"
[ -d "$d" ] || mkdir -m 700 "$d" || exit 3
[ -e "$f" ] || : > "$f" || exit 3
if [ -s "$f" ] && [ "$(tail -c 1 "$f" | wc -l)" -eq 0 ]; then echo >> "$f"; fi
added=0
while IFS= read -r line; do
  [ -n "$line" ] || continue
  blob=${line#* }
  blob=${blob%% *}
  if grep -qF -e "$blob" "$f"; then continue; fi
  printf '%s\n' "$line" >> "$f" || exit 4
  added=$((added + 1))
done
echo "added=$added"
"""
READ = "cat ~/.ssh/authorized_keys 2>/dev/null || true"


def fetch():
    """{"who": the account's name, "keys": [...]} from the signed-in Bromigos account; None
    when signed out, or when bromigOS's account helper isn't installed. Raises OSError,
    ValueError or bromigos_account.SignInError when the account can't be read."""
    try:
        import bromigos_account as A
        import bromigos_login as L
    except ImportError:
        return None
    keys = L.account_ssh_keys()
    if keys is None:
        return None
    return {"who": A.status(L.PROVIDER).get("who"), "keys": keys, "site": L.site_name()}


def command():
    """The command that appends the keys it reads on stdin, one authorized_keys line each."""
    return shlex.join(["sh", "-c", SCRIPT])


def on_box(text):
    """The key blobs an authorized_keys file already holds (options and comments ignored)."""
    blobs = set()
    for line in (text or "").splitlines():
        for word in line.split():
            if word.startswith("AAAA"):
                blobs.add(word)
                break
    return blobs


def added(out):
    """How many keys the script added, from its last line ("added=2")."""
    for line in reversed((out or "").splitlines()):
        if line.startswith("added="):
            return int(line[6:]) if line[6:].isdigit() else 0
    return 0


def lines(keys):
    """The keys as the script reads them on stdin."""
    return "".join(k["line"] + "\n" for k in keys)


def describe(key):
    return f"{key['fingerprint']}  {key['type'].replace('ssh-', '').replace('@openssh.com', '')}" + \
        (f"  {key['title']}" if key.get("title") else "")


def offer(say, yes, run, user, account, skip=(), password=False):
    """Offer the account's keys that aren't on the box yet, and add them after a yes.

    say(text) and yes(question) talk to the person; run(command, stdin) -> (code, out, err)
    runs a command on the box as `user`. password: the box doesn't take a key yet, so run
    asks for the box's password once and nothing is read from the box first. skip: the
    fingerprints the person said no to before. Returns (fingerprints added, fingerprints
    declined)."""
    keys = account["keys"]
    who = account.get("who")
    if not keys:
        say(f"  Your Bromigos account{f' ({who})' if who else ''} has no SSH keys. Add one at "
            f"{account.get('site') or 'account.bromigos.org'} › SSH keys to have bromigOS put it on new boxes.")
        return [], []
    there = set()
    if not password:
        code, out, _ = run(READ, None)
        there = on_box(out) if code == 0 else set()
    have = [k for k in keys if k["blob"] in there]
    new = [k for k in keys if k["blob"] not in there and k["fingerprint"] not in skip]
    if not new:
        if have:
            say(f"  ✓ Your Bromigos account's SSH keys are on the box ({len(have)} of {len(keys)})")
        return [], []
    say(f"  You're signed in to your Bromigos account{f' as {who}' if who else ''}. These SSH keys on it "
        f"aren't on the box yet:")
    for k in new:
        say("    " + describe(k))
    say(f"  bromigOS can add them to ~/.ssh/authorized_keys for {user} on the box, so these keys can log in.")
    say("  It only adds lines. The keys already there stay as they are.")
    if password:
        say("  It asks for your password on the box once.")
    if not yes(f"  Add {'this key' if len(new) == 1 else f'these {len(new)} keys'}?"):
        say("  Skipped. bromigOS won't ask about these keys for this box again.")
        return [], [k["fingerprint"] for k in new]
    code, out, _ = run(command(), lines(new))
    if code:
        say("  Couldn't add them: the box said no. Nothing was removed from it.")
        return [], []
    n = added(out)
    say(f"  ✓ Added {n} SSH key{'s' if n != 1 else ''} from your Bromigos account to {user}'s authorized_keys")
    return [k["fingerprint"] for k in new], []
