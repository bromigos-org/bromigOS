#!/usr/bin/env bash
# BRODEC's desktop app (brodec-desktop) for [bromigos]: packaging/README.md, "BRODEC's desktop
# app". BRODEC's repository is private. Its CI builds the package and leaves it, unsigned, as
# the only file of the commit at its git ref refs/brodec-desktop/package. The commit's message
# names the file, the source commit and the file's SHA-256:
#
#   brodec-desktop-<pkgver>-<pkgrel>-x86_64.pkg.tar.zst
#
#   source: <the BRODEC commit it was built from>
#   sha256: <the file's SHA-256>
#
# This script reads that ref with a read-only deploy key and checks it. publish.sh
# (PKGS_PREBUILT) then signs the package and adds it to each channel.
#
#   brodec-desktop.sh staged         the staged file's name and source commit (nothing: none)
#   brodec-desktop.sh missing FILE   the channels whose public database doesn't list FILE
#   brodec-desktop.sh fetch DIR      fetch the staged package into DIR, after every check below
#
# fetch refuses the package unless:
#   - the ref's commit holds that one file, with the SHA-256 its message gives;
#   - the source commit is on BRODEC's main branch;
#   - the source commit has no desktop/brodec_desktop/ (BRODEC's old desktop app, which is
#     never published), and neither has the package;
#   - the package is brodec-desktop for x86_64, and its version names the source commit.
#
# Environment (never printed):
#   BRODEC_DEPLOY_KEY   the deploy key (an SSH private key) that may read BRODEC's repository
#   BRODEC_GIT_URL      default git@github.com:bromigos-org/brodec.git (a test sets a file:// one)
#   PKGS_PUBLIC_URL     default https://pkgs.bromigos.org: where `missing` reads the databases
set -euo pipefail

ref=refs/brodec-desktop/package
url=${BRODEC_GIT_URL:-git@github.com:bromigos-org/brodec.git}
public=${PKGS_PUBLIC_URL:-https://pkgs.bromigos.org}
channels=(edge rc stable)
name_re='^brodec-desktop-[A-Za-z0-9._+]+-[0-9.]+-x86_64\.pkg\.tar\.zst$'

die() { echo "brodec-desktop: $*" >&2; exit 1; }
out() {   # out KEY VALUE: to the step's outputs in CI, and to stdout
  echo "$1=$2"
  if [[ -n ${GITHUB_OUTPUT:-} ]]; then echo "$1=$2" >> "$GITHUB_OUTPUT"; fi
}

work=$(mktemp -d)
agent=
cleanup() {
  if [[ -n $agent ]]; then SSH_AGENT_PID=$agent ssh-agent -k >/dev/null 2>&1 || true; fi
  rm -rf "$work"
}
trap cleanup EXIT

# The deploy key goes into an ssh-agent of this run's own, from the environment: never a file
# or an argument. GitHub's host key is pinned (https://api.github.com/meta, ssh_keys).
if [[ -n ${BRODEC_DEPLOY_KEY:-} ]]; then
  eval "$(ssh-agent -s)" >/dev/null
  agent=$SSH_AGENT_PID
  ssh-add -q - <<<"$BRODEC_DEPLOY_KEY" 2>/dev/null || die "the deploy key didn't load"
  echo 'github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl' \
    > "$work/known_hosts"
  export GIT_SSH_COMMAND="ssh -o UserKnownHostsFile=$work/known_hosts -o StrictHostKeyChecking=yes -o IdentitiesOnly=no -o BatchMode=yes"
fi
unset BRODEC_DEPLOY_KEY

g() { git -C "$work/git" "$@"; }
git init -q "$work/git"
g remote add origin "$url"

# The staged commit's id, or nothing when nothing is staged.
staged_commit() { g ls-remote origin "$ref" | awk '{ print $1 }'; }

# Fetch the staged commit alone (no tree, no file) and read its message.
staged_message() {
  local c=$1
  g fetch -q --depth=1 --filter=tree:0 origin "$ref" 2>/dev/null || g fetch -q --depth=1 origin "$ref"
  [[ "$(g rev-parse FETCH_HEAD)" == "$c" ]] || die "the ref moved while it was read; try again"
  g log -1 --format=%B FETCH_HEAD
}

field() { awk -v k="$1:" '$1 == k { print $2; exit }'; }

cmd=${1:-}
case "$cmd" in
  staged)
    c=$(staged_commit)
    if [[ -z $c ]]; then
      echo "brodec-desktop: nothing is staged at $ref"
      out file ""
      exit 0
    fi
    msg=$(staged_message "$c")
    file=$(head -1 <<<"$msg")
    [[ $file =~ $name_re ]] || die "the staged commit's first line isn't a brodec-desktop package name"
    out file "$file"
    out source "$(field source <<<"$msg")"
    ;;

  missing)
    file=${2:?usage: brodec-desktop.sh missing FILE}
    [[ $file =~ $name_re ]] || die "$file isn't a brodec-desktop package name"
    missing=()
    for ch in "${channels[@]}"; do
      if [[ $ch == edge ]]; then p=bromigos/x86_64; else p=bromigos/$ch/x86_64; fi
      if ! curl -fsSL --retry 3 -o "$work/$ch.db" "$public/$p/bromigos.db"; then
        missing+=("$ch"); continue   # can't read it: publish.sh will tell
      fi
      # (lists go to a file first: grep -q stopping early would fail the pipe under pipefail)
      tar -xzOf "$work/$ch.db" --wildcards '*/desc' | awk '/^%FILENAME%$/ { getline; print }' > "$work/$ch.names" \
        || : > "$work/$ch.names"
      grep -qxF "$file" "$work/$ch.names" || missing+=("$ch")
    done
    out channels "${missing[*]}"
    ;;

  fetch)
    dir=${2:?usage: brodec-desktop.sh fetch DIR}
    mkdir -p "$dir"
    c=$(staged_commit)
    [[ -n $c ]] || die "nothing is staged at $ref"
    g fetch -q --depth=1 origin "$ref"
    [[ "$(g rev-parse FETCH_HEAD)" == "$c" ]] || die "the ref moved while it was read; try again"
    msg=$(g log -1 --format=%B "$c")
    file=$(head -1 <<<"$msg")
    source=$(field source <<<"$msg")
    sum=$(field sha256 <<<"$msg")
    [[ $file =~ $name_re ]] || die "the staged commit's first line isn't a brodec-desktop package name"
    [[ $source =~ ^[0-9a-f]{40}$ ]] || die "the staged commit names no source commit"
    [[ $sum =~ ^[0-9a-f]{64}$ ]] || die "the staged commit gives no SHA-256"

    # The commit holds that one file.
    entries=$(g ls-tree "$c")
    [[ $(wc -l <<<"$entries") == 1 && $entries == *$'\t'"$file" ]] \
      || die "the staged commit should hold $file and nothing else"
    g cat-file blob "$c:$file" > "$work/$file"
    [[ "$(sha256sum "$work/$file" | cut -d' ' -f1)" == "$sum" ]] || die "$file's SHA-256 isn't the one its commit gives"

    # The source commit is on main (commits only: no trees, no files).
    g fetch -q --filter=tree:0 origin "+refs/heads/main:refs/remotes/origin/main"
    g merge-base --is-ancestor "$source" origin/main 2>/dev/null \
      || die "the source commit ${source:0:12} isn't on BRODEC's main branch"

    # The gate: the old desktop app is never published. Its folder must be gone from the
    # source commit (trees only: no file is downloaded).
    g fetch -q --depth=1 --filter=blob:none origin "$source"
    if [[ -n "$(g ls-tree -d "$source" desktop/brodec_desktop)" ]]; then
      die "the source commit ${source:0:12} still has desktop/brodec_desktop/ (the old desktop app): not published"
    fi

    # The package itself.
    info=$(bsdtar -xOf "$work/$file" .PKGINFO)
    pkgname=$(awk -F' = ' '$1 == "pkgname" { print $2; exit }' <<<"$info")
    pkgver=$(awk -F' = ' '$1 == "pkgver" { print $2; exit }' <<<"$info")
    arch=$(awk -F' = ' '$1 == "arch" { print $2; exit }' <<<"$info")
    [[ $pkgname == brodec-desktop && $arch == x86_64 ]] || die "$file is $pkgname for $arch, not brodec-desktop for x86_64"
    [[ $file == "brodec-desktop-$pkgver-x86_64.pkg.tar.zst" ]] || die "$file's name doesn't match its version, $pkgver"
    if [[ $pkgver =~ \.g([0-9a-f]{7,40})- ]]; then
      [[ $source == "${BASH_REMATCH[1]}"* ]] || die "$file names commit ${BASH_REMATCH[1]}, not the source ${source:0:12}"
    fi
    bsdtar -tf "$work/$file" > "$work/contents"
    if grep -Eq '(^|/)brodec_desktop(/|$)' "$work/contents"; then
      die "$file carries brodec_desktop/ (the old desktop app): not published"
    fi

    mv "$work/$file" "$dir/$file"
    echo "brodec-desktop: $file (from ${source:0:12}) checked"
    out file "$file"
    ;;

  *)
    sed -n '2,32p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 2
    ;;
esac
