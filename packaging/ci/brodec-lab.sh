#!/usr/bin/env bash
# BRODEC's lab bridge, brodec-lab: packaging/README.md, "BRODEC's lab bridge". BRODEC's
# repository is private. Its CI builds the bridge and leaves it, as a tarball, as the only file
# of the commit at its git ref refs/brodec-lab/build. The commit's message names the file, the
# source commit, the version and the file's SHA-256:
#
#   brodec-lab-<version>-x86_64.tar.gz
#
#   source: <the BRODEC commit it was built from>
#   version: <version>
#   sha256: <the file's SHA-256>
#
# This script reads that ref with a read-only deploy key and checks it. The workflow
# (.github/workflows/brodec-lab.yml) then publishes the image, the Helm chart and the package.
#
#   brodec-lab.sh staged          the staged file, its version and source commit (nothing: none)
#   brodec-lab.sh missing VERSION what isn't published yet: image, chart, channels
#   brodec-lab.sh fetch DIR       fetch the staged tarball, check it, unpack the binary into DIR
#   brodec-lab.sh package DIR OUT build the pacman package from DIR (after fetch) into OUT
#   brodec-lab.sh chart-version VERSION   the chart version for a bridge version
#
# fetch refuses the tarball unless:
#   - the ref's commit holds that one file, with the SHA-256 its message gives;
#   - the source commit is on BRODEC's main branch, and the version names it;
#   - the tarball holds exactly brodec-lab, README and VERSION under one folder, and
#     brodec-lab is an x86-64 ELF program.
#
# Environment (never printed):
#   BRODEC_DEPLOY_KEY   the deploy key (an SSH private key) that may read BRODEC's repository
#   BRODEC_GIT_URL      default git@github.com:bromigos-org/brodec.git (a test sets a file:// one)
#   PKGS_PUBLIC_URL     default https://pkgs.bromigos.org: where `missing` reads the databases
#   GHCR_TOKEN          for `missing`: a token that may read the org's packages (GITHUB_TOKEN);
#                       without it the image and the chart count as missing
#   REGISTRY            default ghcr.io/bromigos-org
set -euo pipefail

ref=refs/brodec-lab/build
url=${BRODEC_GIT_URL:-git@github.com:bromigos-org/brodec.git}
public=${PKGS_PUBLIC_URL:-https://pkgs.bromigos.org}
registry=${REGISTRY:-ghcr.io/bromigos-org}
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root=$(cd "$here/../.." && pwd)
chart_dir=$root/homelab/charts/brodec-lab
channels=(edge rc stable)
ver_re='[0-9]+\.[0-9]+\.[0-9]+\.r([0-9]+)\.g([0-9a-f]{7,40})'
name_re="^brodec-lab-($ver_re)-x86_64\\.tar\\.gz$"

die() { echo "brodec-lab: $*" >&2; exit 1; }
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

# The chart's version for a bridge version: the chart's own major.minor (Chart.yaml) and the
# bridge's build number, so every new bridge is a new chart and a chart change bumps the minor.
chart_version() {
  [[ $1 =~ ^$ver_re$ ]] || die "$1 isn't a brodec-lab version"
  local n=${BASH_REMATCH[1]} base
  base=$(sed -n 's/^version: *\([0-9]*\.[0-9]*\)\..*/\1/p' "$chart_dir/Chart.yaml")
  [[ -n $base ]] || die "no version in $chart_dir/Chart.yaml"
  echo "$base.$n"
}

case "${1:-}" in
  chart-version)
    out chart_version "$(chart_version "${2:?usage: brodec-lab.sh chart-version VERSION}")"
    exit 0 ;;
  package)
    dir=${2:?usage: brodec-lab.sh package DIR OUT}
    dest=${3:?usage: brodec-lab.sh package DIR OUT}
    [[ -x $dir/brodec-lab && -f $dir/VERSION ]] || die "$dir has no checked bridge (run fetch first)"
    version=$(awk '$1 == "version:" { print $2; exit }' "$dir/VERSION")
    [[ $version =~ ^$ver_re$ ]] || die "$dir/VERSION names no version"
    mkdir -p "$dest"
    dest=$(cd "$dest" && pwd)
    build=$work/pkg
    cp -r "$root/packaging/prebuilt/brodec-lab" "$build"
    cp "$dir/brodec-lab" "$build/brodec-lab.bin"
    sed -i "s/^pkgver=.*/pkgver=$version/" "$build/PKGBUILD"
    (cd "$build" && PKGDEST="$dest" makepkg --noconfirm --cleanbuild --force --nodeps)
    ls -l "$dest"
    exit 0 ;;
esac

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

staged_commit() { g ls-remote origin "$ref" | awk '{ print $1 }'; }
field() { awk -v k="$1:" '$1 == k { print $2; exit }'; }

# Does the registry have this tag? Anonymous for a public package, else with GHCR_TOKEN.
has_tag() {   # has_tag REPOSITORY TAG
  local repo=$1 tag=$2 token
  local auth=()
  if [[ -n ${GHCR_TOKEN:-} ]]; then auth=(-u "x:$GHCR_TOKEN"); fi
  token=$(curl -fsS "${auth[@]}" "https://ghcr.io/token?scope=repository:${registry#ghcr.io/}/$repo:pull" 2>/dev/null \
    | sed -n 's/.*"token":"\([^"]*\)".*/\1/p') || return 1
  [[ -n $token ]] || return 1
  curl -fsS -o /dev/null -I \
    -H "Authorization: Bearer $token" \
    -H 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json, application/vnd.docker.distribution.manifest.list.v2+json' \
    "https://ghcr.io/v2/${registry#ghcr.io/}/$repo/manifests/$tag" 2>/dev/null
}

case "$1" in
  staged)
    c=$(staged_commit)
    if [[ -z $c ]]; then
      echo "brodec-lab: nothing is staged at $ref"
      out file ""
      exit 0
    fi
    g fetch -q --depth=1 --filter=tree:0 origin "$ref" 2>/dev/null || g fetch -q --depth=1 origin "$ref"
    [[ "$(g rev-parse FETCH_HEAD)" == "$c" ]] || die "the ref moved while it was read; try again"
    msg=$(g log -1 --format=%B FETCH_HEAD)
    file=$(head -1 <<<"$msg")
    [[ $file =~ $name_re ]] || die "the staged commit's first line isn't a brodec-lab tarball name"
    out file "$file"
    out version "${BASH_REMATCH[1]}"
    out source "$(field source <<<"$msg")"
    ;;

  missing)
    version=${2:?usage: brodec-lab.sh missing VERSION}
    [[ $version =~ ^$ver_re$ ]] || die "$version isn't a brodec-lab version"
    cv=$(chart_version "$version")
    if has_tag brodec-lab "$version"; then out image ""; else out image "$version"; fi
    if has_tag charts/brodec-lab "$cv"; then out chart ""; else out chart "$cv"; fi
    pkg="brodec-lab-$version-1-x86_64.pkg.tar.zst"
    missing=()
    for ch in "${channels[@]}"; do
      if [[ $ch == edge ]]; then p=bromigos/x86_64; else p=bromigos/$ch/x86_64; fi
      if ! curl -fsSL --retry 3 -o "$work/$ch.db" "$public/$p/bromigos.db"; then
        missing+=("$ch"); continue   # can't read it: publish.sh will tell
      fi
      tar -xzOf "$work/$ch.db" --wildcards '*/desc' | awk '/^%FILENAME%$/ { getline; print }' > "$work/$ch.names" \
        || : > "$work/$ch.names"
      grep -qxF "$pkg" "$work/$ch.names" || missing+=("$ch")
    done
    out channels "${missing[*]}"
    ;;

  fetch)
    dir=${2:?usage: brodec-lab.sh fetch DIR}
    mkdir -p "$dir"
    c=$(staged_commit)
    [[ -n $c ]] || die "nothing is staged at $ref"
    g fetch -q --depth=1 origin "$ref"
    [[ "$(g rev-parse FETCH_HEAD)" == "$c" ]] || die "the ref moved while it was read; try again"
    msg=$(g log -1 --format=%B "$c")
    file=$(head -1 <<<"$msg")
    source=$(field source <<<"$msg")
    sum=$(field sha256 <<<"$msg")
    [[ $file =~ $name_re ]] || die "the staged commit's first line isn't a brodec-lab tarball name"
    version=${BASH_REMATCH[1]}
    hash=${BASH_REMATCH[3]}
    [[ $source =~ ^[0-9a-f]{40}$ ]] || die "the staged commit names no source commit"
    [[ $sum =~ ^[0-9a-f]{64}$ ]] || die "the staged commit gives no SHA-256"
    [[ $source == "$hash"* ]] || die "$file names commit $hash, not the source ${source:0:12}"

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

    # The tarball: exactly the bridge, README and VERSION, under one folder.
    top=${file%.tar.gz}
    want=$(printf '%s/\n%s/README\n%s/VERSION\n%s/brodec-lab\n' "$top" "$top" "$top" "$top")
    [[ "$(tar -tzf "$work/$file" | LC_ALL=C sort)" == "$want" ]] \
      || die "$file doesn't hold exactly brodec-lab, README and VERSION"
    tar -xzf "$work/$file" -C "$work" --no-same-owner
    bin=$work/$top/brodec-lab
    [[ -f $bin && ! -L $bin ]] || die "$file's brodec-lab isn't a plain file"
    # ELF, 64-bit, little-endian, x86-64 (e_machine 0x3e).
    [[ "$(od -An -tx1 -N20 "$bin" | tr -d ' \n')" =~ ^7f454c46020101.{22}3e00$ ]] \
      || die "$file's brodec-lab isn't an x86-64 Linux program"
    [[ "$(field version < "$work/$top/VERSION")" == "$version" && "$(field source < "$work/$top/VERSION")" == "$source" ]] \
      || die "$file's VERSION doesn't match its name and source"

    install -m755 "$bin" "$dir/brodec-lab"
    install -m644 "$work/$top/VERSION" "$dir/VERSION"
    echo "brodec-lab: $file (from ${source:0:12}) checked"
    out file "$file"
    out version "$version"
    ;;

  *)
    sed -n '2,36p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 2
    ;;
esac
