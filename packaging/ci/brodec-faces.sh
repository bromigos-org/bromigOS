#!/usr/bin/env bash
# THE CUFF for Watch Face Push: packaging/README.md, "BRODEC's watch faces". BRODEC's watch app
# downloads its watch face on demand from https://pkgs.bromigos.org/brodec/faces/ and installs it
# with Wear OS 6's Watch Face Push. BRODEC's repository is private. Its release CI builds the face,
# runs Google's Watch Face Push validator on it and stages the result as the only content of a
# parentless commit at its git ref refs/brodec-faces/build:
#
#   latest.json                  the faces manifest the watch reads
#   <versionName>/<face>.apk     each face's APK, at the path latest.json names
#   <versionName>/<face>.token   its validation token (also in latest.json)
#
# The commit's message:
#
#   brodec-faces <versionName>
#
#   source: <the BRODEC commit it was built from>
#   version: <versionName>
#   versionCode: <versionCode>
#   manifest-sha256: <latest.json's SHA-256>
#
# This script reads that ref with a read-only deploy key, checks it, and publishes it. The
# workflow is .github/workflows/brodec-faces.yml.
#
#   brodec-faces.sh staged         the staged version, versionCode and source commit
#   brodec-faces.sh missing CODE   publish=true when the published latest.json is older than CODE
#   brodec-faces.sh fetch DIR      fetch the staged files into DIR and check them
#   brodec-faces.sh publish DIR    upload DIR (after fetch): the APKs and tokens, then latest.json
#
# fetch refuses the files unless:
#   - latest.json's SHA-256 is the one the message gives, and its faces share that version;
#   - every face is a Watch Face Push package of BRODEC's app (org.bromigos.brodec.watchfacepush.*),
#     and its APK has the size and SHA-256 latest.json gives, and its token matches;
#   - each APK holds only AndroidManifest.xml, resources.arsc, res/ and META-INF/ (what Watch
#     Face Push takes: a watch face with no code);
#   - the commit holds those files and nothing else;
#   - the source commit is on BRODEC's main branch.
#
# Environment (never printed):
#   BRODEC_DEPLOY_KEY   the deploy key (an SSH private key) that may read BRODEC's repository
#   BRODEC_GIT_URL      default git@github.com:bromigos-org/brodec.git (the test sets a file:// one)
#   PKGS_PUBLIC_URL     default https://pkgs.bromigos.org: where `missing` reads latest.json
#   FACES_PREFIX        default brodec/faces: the folder in the bucket (the test's own folder)
#   PKGS_PUBLIC_ENDPOINT, PKGS_PUBLIC_BUCKET, PKGS_PUBLIC_ACCESS_KEY_ID,
#   PKGS_PUBLIC_SECRET_ACCESS_KEY   for publish: the public bucket (R2)
set -euo pipefail

ref=refs/brodec-faces/build
url=${BRODEC_GIT_URL:-git@github.com:bromigos-org/brodec.git}
public=${PKGS_PUBLIC_URL:-https://pkgs.bromigos.org}
prefix=${FACES_PREFIX:-brodec/faces}

die() { echo "brodec-faces: $*" >&2; exit 1; }
out() {   # out KEY VALUE: to the step's outputs in CI, and to stdout
  echo "$1=$2"
  if [[ -n ${GITHUB_OUTPUT:-} ]]; then echo "$1=$2" >> "$GITHUB_OUTPUT"; fi
}
field() { awk -v k="$1:" '$1 == k { print $2; exit }'; }

work=$(mktemp -d)
agent=
cleanup() {
  if [[ -n $agent ]]; then SSH_AGENT_PID=$agent ssh-agent -k >/dev/null 2>&1 || true; fi
  rm -rf "$work"
}
trap cleanup EXIT

case "${1:-}" in
  missing)
    code=${2:?usage: brodec-faces.sh missing VERSIONCODE}
    [[ $code =~ ^[0-9]+$ ]] || die "$code isn't a versionCode"
    have=0
    if curl -fsSL --retry 3 -o "$work/latest.json" "$public/$prefix/latest.json" 2>/dev/null; then
      have=$(python3 -I -c 'import json,sys; print(max((f["versionCode"] for f in json.load(open(sys.argv[1]))["faces"]), default=0))' "$work/latest.json" 2>/dev/null || echo 0)
    fi
    if (( code > have )); then out publish true; else out publish false; fi
    out published "$have"
    exit 0 ;;
  publish)
    dir=${2:?usage: brodec-faces.sh publish DIR}
    [[ -f $dir/latest.json && -f $dir/.checked ]] || die "$dir has no checked faces (run fetch first)"
    for v in PKGS_PUBLIC_ENDPOINT PKGS_PUBLIC_BUCKET PKGS_PUBLIC_ACCESS_KEY_ID PKGS_PUBLIC_SECRET_ACCESS_KEY; do
      [[ -n ${!v:-} ]] || die "$v isn't set"
    done
    command -v rclone >/dev/null || die "rclone is needed"
    export RCLONE_CONFIG_PUB_TYPE=s3 RCLONE_CONFIG_PUB_PROVIDER=Cloudflare RCLONE_CONFIG_PUB_REGION=auto \
      RCLONE_CONFIG_PUB_NO_CHECK_BUCKET=true RCLONE_CONFIG_PUB_ENDPOINT=$PKGS_PUBLIC_ENDPOINT \
      RCLONE_CONFIG_PUB_ACCESS_KEY_ID=$PKGS_PUBLIC_ACCESS_KEY_ID RCLONE_CONFIG_PUB_SECRET_ACCESS_KEY=$PKGS_PUBLIC_SECRET_ACCESS_KEY
    unset PKGS_PUBLIC_ACCESS_KEY_ID PKGS_PUBLIC_SECRET_ACCESS_KEY
    rcl() { rclone --config /dev/null --stats 0 "$@"; }
    B="pub:$PKGS_PUBLIC_BUCKET/$prefix"
    # The APKs and tokens first (a version's files never change), latest.json last, so the
    # manifest never names an APK that isn't there yet.
    while IFS= read -r f; do
      case $f in
        *.apk) type=application/vnd.android.package-archive ;;
        *) type="text/plain; charset=utf-8" ;;
      esac
      rcl copyto --header-upload "Content-Type: $type" --header-upload "Cache-Control: public, max-age=31536000, immutable" \
        "$dir/$f" "$B/$f"
      echo "brodec-faces: published $prefix/$f"
    done < <(cd "$dir" && find . -mindepth 2 -type f | sed 's|^\./||' | LC_ALL=C sort)
    rcl copyto --header-upload "Content-Type: application/json" --header-upload "Cache-Control: no-cache" \
      "$dir/latest.json" "$B/latest.json"
    echo "brodec-faces: published $prefix/latest.json ($public/$prefix/latest.json)"
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

case "$1" in
  staged)
    c=$(staged_commit)
    if [[ -z $c ]]; then
      echo "brodec-faces: nothing is staged at $ref"
      out version ""
      exit 0
    fi
    g fetch -q --depth=1 --filter=tree:0 origin "$ref" 2>/dev/null || g fetch -q --depth=1 origin "$ref"
    [[ "$(g rev-parse FETCH_HEAD)" == "$c" ]] || die "the ref moved while it was read; try again"
    msg=$(g log -1 --format=%B FETCH_HEAD)
    [[ "$(head -1 <<<"$msg")" =~ ^brodec-faces\ [0-9A-Za-z.\-]+$ ]] || die "the staged commit isn't a brodec-faces release"
    code=$(field versionCode <<<"$msg")
    [[ $code =~ ^[0-9]+$ ]] || die "the staged commit gives no versionCode"
    out version "$(field version <<<"$msg")"
    out version_code "$code"
    out source "$(field source <<<"$msg")"
    ;;

  fetch)
    dir=${2:?usage: brodec-faces.sh fetch DIR}
    mkdir -p "$dir"
    c=$(staged_commit)
    [[ -n $c ]] || die "nothing is staged at $ref"
    g fetch -q --depth=1 origin "$ref"
    [[ "$(g rev-parse FETCH_HEAD)" == "$c" ]] || die "the ref moved while it was read; try again"
    msg=$(g log -1 --format=%B "$c")
    version=$(field version <<<"$msg")
    code=$(field versionCode <<<"$msg")
    source=$(field source <<<"$msg")
    sum=$(field manifest-sha256 <<<"$msg")
    [[ "$(head -1 <<<"$msg")" == "brodec-faces $version" ]] || die "the staged commit isn't a brodec-faces release"
    [[ $version =~ ^[0-9A-Za-z.\-]+$ ]] || die "the staged commit names no version"
    [[ $code =~ ^[0-9]+$ ]] || die "the staged commit gives no versionCode"
    [[ $source =~ ^[0-9a-f]{40}$ ]] || die "the staged commit names no source commit"
    [[ $sum =~ ^[0-9a-f]{64}$ ]] || die "the staged commit gives no SHA-256 for latest.json"

    g archive "$c" | tar -x -C "$dir"
    [[ "$(sha256sum "$dir/latest.json" | cut -d' ' -f1)" == "$sum" ]] || die "latest.json's SHA-256 isn't the one its commit gives"
    python3 -I - "$dir" "$version" "$code" <<'PY' || die "the staged faces didn't check out"
import hashlib, json, os, re, sys, zipfile
d, version, code = sys.argv[1], sys.argv[2], int(sys.argv[3])
def fail(why): sys.exit(f"brodec-faces: {why}")
m = json.load(open(os.path.join(d, "latest.json")))
if m.get("schema") != 1 or not m.get("faces"): fail("latest.json has no faces (schema 1)")
want = {"latest.json"}
for f in m["faces"]:
    if f.get("versionName") != version or f.get("versionCode") != code: fail(f"{f.get('id')} isn't version {version} ({code})")
    if not re.fullmatch(r"org\.bromigos\.brodec\.watchfacepush\.[a-z0-9_]+", f.get("package", "")): fail(f"{f.get('package')} isn't BRODEC's Watch Face Push package")
    apk = f.get("apk", "")
    if not re.fullmatch(re.escape(version) + r"/[a-z0-9_]+\.apk", apk): fail(f"{apk} isn't {version}/<face>.apk")
    p = os.path.join(d, apk)
    if not os.path.isfile(p) or os.path.islink(p): fail(f"{apk} is missing")
    data = open(p, "rb").read()
    if len(data) != f.get("size") or hashlib.sha256(data).hexdigest() != f.get("sha256"): fail(f"{apk} doesn't match its size and SHA-256")
    names = zipfile.ZipFile(p).namelist()
    bad = [n for n in names if not (n in ("AndroidManifest.xml", "resources.arsc") or n.startswith(("res/", "META-INF/")))]
    if bad or "AndroidManifest.xml" not in names: fail(f"{apk} holds more than a code-free watch face: {bad[:5]}")
    tok = apk[:-4] + ".token"
    if open(os.path.join(d, tok)).read().strip() != f.get("token") or not f.get("token"): fail(f"{tok} isn't the token in latest.json")
    want |= {apk, tok}
have = set()
for root, dirs, files in os.walk(d):
    for n in files:
        have.add(os.path.relpath(os.path.join(root, n), d))
if have != want: fail(f"the staged commit holds other files: {sorted(have ^ want)[:5]}")
PY

    # The source commit is on main (commits only: no trees, no files).
    g fetch -q --filter=tree:0 origin "+refs/heads/main:refs/remotes/origin/main"
    g merge-base --is-ancestor "$source" origin/main 2>/dev/null \
      || die "the source commit ${source:0:12} isn't on BRODEC's main branch"

    touch "$dir/.checked"
    echo "brodec-faces: $version ($code, from ${source:0:12}) checked"
    out version "$version"
    out version_code "$code"
    ;;

  *)
    sed -n '2,46p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 2
    ;;
esac
