#!/usr/bin/env bash
# bromigOS bootstrap, on a fresh Arch install, as your own user (it uses sudo). Download it,
# read it, then run it:
#
#   curl -fsSLO <repo>/bromigos/install.sh    (a repository with its own CA: curl --cacert FILE)
#   bash install.sh --repo <repo> [options] [-- bromigos install args]
#
#   --repo URL     the package repository's base URL (pacman Server is URL/$repo/$arch);
#                  or BROMIGOS_REPO_URL; default: the public repository, once there is one
#   --ca FILE|URL  a CA certificate to trust for the repository's TLS (a homelab's own CA)
#   --channel NAME stable (default: tagged releases), rc, or edge (every push to main);
#                  `bromigos channel` switches later (docs/update.md)
#   --dry-run      say what it would do; change nothing
#
# Piped (curl … | bash -s -- --repo <repo>), it asks on the terminal, not the pipe. With no
# terminal at all it needs --yes, and runs unattended.
# It adds the [bromigos] repository and trusts its signing key (fingerprint pinned below),
# installs bromigos-keyring and bromigos-core, then hands over to `bromigos install`, which
# does the rest (docs/install.md). Safe to run again. Logs to ~/.local/state/bromigos/install.log.
set -euo pipefail
FPR=393E7D54F7DE58FE75B97214947C9D6193D3DD8B
PUBLIC_REPO=''   # the public repository's base URL; empty during early access (docs/public.md)
say() { printf 'install.sh: %s\n' "$*" | tee -a "$log"; }
run() { if ((dry)); then say "would run: $*"; else say "run: $*"; "$@"; fi; }

main() {
  repo=${BROMIGOS_REPO_URL:-$PUBLIC_REPO} ca='' channel=${BROMIGOS_CHANNEL:-stable} dry=0 rest=()
  while (($#)); do
    case $1 in
      --repo) repo=$2; shift 2 ;; --ca) ca=$2; shift 2 ;; --channel) channel=$2; shift 2 ;;
      -n|--dry-run) dry=1; rest+=(--dry-run); shift ;;
      -h|--help) sed -n '2,19p' "$0" 2>/dev/null | sed 's/^# \{0,1\}//' || echo "install.sh: its header lists the options"; exit 0 ;;
      --) shift; rest+=("$@"); break ;; *) rest+=("$1"); shift ;;
    esac
  done
  [[ -n $repo ]] || { echo "install.sh: --repo URL (the bromigOS package repository) is required" >&2; exit 2; }
  ((EUID)) || { echo "install.sh: run as your own user, not root (it uses sudo)" >&2; exit 1; }
  command -v pacman >/dev/null || { echo "install.sh: bromigOS installs on Arch Linux (no pacman here)" >&2; exit 1; }
  yes=(); [[ " ${rest[*]} " == *' --yes '* ]] && yes=(--noconfirm)      # unattended: --yes, passed on too
  # Piped, stdin is the rest of this script: pacman and the first-run questions read the
  # terminal instead. No terminal at all: unattended with --yes, else stop.
  if [[ ! -t 0 ]]; then
    if { : </dev/tty; } 2>/dev/null; then exec </dev/tty
    elif ((${#yes[@]} || dry)); then exec </dev/null
    else echo "install.sh: no terminal to ask on; run it in one, or add --yes to install unattended" >&2; exit 2
    fi
  fi
  log=${XDG_STATE_HOME:-$HOME/.local/state}/bromigos/install.log; mkdir -p "${log%/*}"
  ((dry)) || [[ -t 0 ]] || say "no terminal: installing unattended; for the first-run questions, run bromigos setup after you sign in"
  case $channel in
    edge) sub='' ;; stable|rc) sub="/$channel" ;;
    *) echo "install.sh: --channel is stable, rc or edge, not $channel" >&2; exit 2 ;;
  esac
  # shellcheck disable=SC2016 # $repo/$arch are pacman's, kept literal
  server="${repo%/}"'/$repo'"$sub"'/$arch'; base=${repo%/}/bromigos
  tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
  if [[ -n $ca ]]; then                                  # the repository's TLS: a homelab CA
    if [[ $ca == http* ]]; then curl -fsSL "$ca" -o "$tmp/ca.crt"; else cp "$ca" "$tmp/ca.crt"; fi
    run sudo trust anchor --store "$tmp/ca.crt"
  fi
  trusted=(); ((dry)) && [[ -n $ca ]] && trusted=(--cacert "$tmp/ca.crt")   # a dry run doesn't trust it
  curl "${trusted[@]}" -fsSL "$base/bromigos.asc" -o "$tmp/bromigos.asc" \
    || { echo "install.sh: can't fetch $base/bromigos.asc (the URL, or this machine's trust of its TLS: --ca)" >&2; exit 1; }
  got=$(gpg --batch --with-colons --import-options show-only --import "$tmp/bromigos.asc" 2>/dev/null | awk -F: '/^fpr:/ { print $10; exit }')
  [[ $got == "$FPR" ]] || { echo "install.sh: the repository's key is $got, not bromigOS's $FPR; stopping" >&2; exit 1; }
  if ! sudo pacman-key --list-keys "$FPR" >/dev/null 2>&1; then
    run sudo pacman-key --add "$tmp/bromigos.asc"; run sudo pacman-key --lsign-key "$FPR"
  fi
  if ! grep -qx '\[bromigos\]' /etc/pacman.conf; then
    section=$(printf '\n[bromigos]\nSigLevel = Required DatabaseOptional\nServer = %s\n' "$server")
    if ((dry)); then say "would add to /etc/pacman.conf:$section"; else printf '%s\n' "$section" | sudo tee -a /etc/pacman.conf >/dev/null; say "added [bromigos] ($channel) to /etc/pacman.conf"; fi
  fi
  run sudo pacman -Syu --needed "${yes[@]}" bromigos-keyring bromigos-core   # -Syu: never a partial upgrade
  if ((dry)) && ! command -v bromigos >/dev/null; then say "would run: bromigos install ${rest[*]}"; exit 0; fi
  exec bromigos install "${rest[@]}"
}

# On the last line, so bash has read the whole script before any of it runs: a piped copy
# can hand stdin to the terminal without the rest of the script going with it.
main "$@"; exit
