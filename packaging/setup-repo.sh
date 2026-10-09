#!/usr/bin/env bash
# Add the bromigOS pacman repository to this machine, once, as root:
#
#   sudo packaging/setup-repo.sh [--dry-run] <server>
#   sudo BROMIGOS_REPO_URL=<server> packaging/setup-repo.sh [--dry-run]
#
# <server> is the repo's base URL (the script appends /$repo/$arch) or a full
# pacman Server value containing $repo. There is no default: the URL is the
# deployment's, not this repository's.
#
# It:
#   1. checks the server answers with a database;
#   2. trusts the bromigOS signing key: imports packaging/keys/bromigos.asc
#      into pacman's keyring and locally signs it, after checking its
#      fingerprint against the one pinned below;
#   3. writes a [bromigos] section to /etc/pacman.conf
#      (SigLevel = Required DatabaseOptional), replacing an older one;
#   4. runs pacman -Sy, then installs bromigos-keyring, which keeps the key
#      in pacman's keyring from then on (the way archlinux-keyring does).
#
# Safe to run again: each step checks first and changes only what differs.
# --dry-run prints what it would do and changes nothing (no root needed).
set -euo pipefail

FINGERPRINT=393E7D54F7DE58FE75B97214947C9D6193D3DD8B
REPO=bromigos
CONF=${PACMAN_CONF:-/etc/pacman.conf}
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
KEYFILE="$here/keys/bromigos.asc"

dry=0
server=${BROMIGOS_REPO_URL:-}
for arg in "$@"; do
  case "$arg" in
    -n|--dry-run) dry=1 ;;
    -h|--help) sed -n '2,24p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) echo "setup-repo: unknown option $arg" >&2; exit 2 ;;
    *) server=$arg ;;
  esac
done
if [[ -z "$server" ]]; then
  echo "setup-repo: give the repo's URL as an argument or in BROMIGOS_REPO_URL" >&2
  exit 2
fi
# shellcheck disable=SC2016 # $repo/$arch are pacman's variables, kept literal
[[ "$server" == *'$repo'* ]] || server="${server%/}"'/$repo/$arch'
arch=$(uname -m)
db_url=${server//\$repo/$REPO}; db_url=${db_url//\$arch/$arch}/$REPO.db

say() { printf 'setup-repo: %s\n' "$*"; }
run() {
  if (( dry )); then printf 'setup-repo: would run: %s\n' "$*"; else "$@"; fi
}

if (( !dry && EUID != 0 )); then
  echo "setup-repo: run as root (sudo), or with --dry-run" >&2
  exit 1
fi

# 1. The server.
if ! curl -fsS -o /dev/null --head "$db_url"; then
  echo "setup-repo: $db_url does not answer; check the URL and that this machine trusts its TLS certificate" >&2
  exit 1
fi
say "server ok: $db_url"

# 2. The key.
keyfpr=$(gpg --batch --with-colons --import-options show-only --import "$KEYFILE" 2>/dev/null \
  | awk -F: '/^fpr:/ { print $10; exit }')
if [[ "$keyfpr" != "$FINGERPRINT" ]]; then
  echo "setup-repo: $KEYFILE has fingerprint '$keyfpr', expected $FINGERPRINT" >&2
  exit 1
fi
if pacman-key --list-keys "$FINGERPRINT" >/dev/null 2>&1 \
   && pacman-key --list-sigs "$FINGERPRINT" 2>/dev/null | grep -q 'Pacman Keyring Master Key'; then
  say "key $FINGERPRINT is already trusted"
else
  run pacman-key --add "$KEYFILE"
  run pacman-key --lsign-key "$FINGERPRINT"
fi

# 3. pacman.conf: the section as it should be.
section=$(printf '[%s]\nSigLevel = Required DatabaseOptional\nServer = %s\n' "$REPO" "$server")
current=$(awk -v s="[$REPO]" '
  /^\[/ { on = ($0 == s) }
  on && !/^[[:space:]]*(#|$)/ { print }' "$CONF")
if [[ "$current" == "$section" ]]; then
  say "$CONF already has the [$REPO] section"
else
  new=$(mktemp)
  # Drop any old [bromigos] section (up to the next section), append ours.
  awk -v s="[$REPO]" '/^\[/ { skip = ($0 == s) } !skip' "$CONF" > "$new"
  printf '\n%s\n' "$section" >> "$new"
  if (( dry )); then
    say "would change $CONF:"
    diff -u "$CONF" "$new" || true
    rm -f "$new"
  else
    [[ -e "$CONF.bromigos.bak" ]] || cp -a "$CONF" "$CONF.bromigos.bak"
    install -m 0644 "$new" "$CONF"
    rm -f "$new"
    say "wrote the [$REPO] section to $CONF (backup: $CONF.bromigos.bak)"
  fi
fi

# 4. Sync, then the keyring package. bromigos-keyring has no dependencies,
# so installing it right after -Sy upgrades nothing else.
run pacman -Sy
run pacman -S --needed --noconfirm bromigos-keyring
say "done: pacman -S bromigos-core installs the bromigos CLI"
