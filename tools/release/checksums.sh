#!/usr/bin/env bash
# The packages' checksums for a GitHub Release (docs/release.md): every package the channel's
# signed database names, bromigOS's and VECTOR's, as SHA256SUMS, signed with the repository's
# key (SHA256SUMS.sig, a detached signature) when the key is in the environment.
#
#   tools/release/checksums.sh CHANNEL OUTDIR [--now] VERSION
#
# Without --now it waits (up to 30 min) until the database names this release's own
# bromigos, bromigos-core and bromigos-vector (VERSION.r…), so the sums are the release's.
# The database's signature is checked against packaging/keys/bromigos.asc first.
#
# Environment (never printed): PKGS_S3_ENDPOINT, PKGS_S3_BUCKET, PKGS_S3_ACCESS_KEY_ID,
# PKGS_S3_SECRET_ACCESS_KEY (read access is enough), or with PKGS_PRIMARY=public the
# PKGS_PUBLIC_* ones (packaging/ci/publish.sh); PKGS_GPG_PRIVATE_KEY and PKGS_GPG_PASSPHRASE
# to sign. PKGS_REPO=bromigos PKGS_ARCH=x86_64.
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root=$(cd "$here/../.." && pwd)
channel=${1:?CHANNEL} out=${2:?OUTDIR}
shift 2
now=0
[[ ${1:-} == --now ]] && { now=1; shift; }
version=${1:?VERSION}
repo=${PKGS_REPO:-bromigos} arch=${PKGS_ARCH:-x86_64}
case "$channel" in
  edge) prefix="$repo/$arch" ;;
  stable|rc) prefix="$repo/$channel/$arch" ;;
  *) echo "checksums: no channel $channel" >&2; exit 2 ;;
esac
# The bucket publish.sh treats as the primary: PKGS_S3_* by default, PKGS_PUBLIC_* with
# PKGS_PRIMARY=public (GitHub's hosted runners).
if [[ ${PKGS_PRIMARY:-s3} == public ]]; then
  v=PKGS_PUBLIC provider=Cloudflare region=auto
else
  v=PKGS_S3 provider=Other region=us-east-1
fi
for s in ENDPOINT BUCKET ACCESS_KEY_ID SECRET_ACCESS_KEY; do
  n="${v}_$s"
  [[ -n "${!n:-}" ]] || { echo "checksums: $n is not set" >&2; exit 2; }
done
endpoint="${v}_ENDPOINT" bucket="${v}_BUCKET" akid="${v}_ACCESS_KEY_ID" secret="${v}_SECRET_ACCESS_KEY"

work=$(mktemp -d)
export GNUPGHOME="$work/gnupg"
trap 'gpgconf --kill all >/dev/null 2>&1 || true; rm -rf "$work"' EXIT
mkdir -m 700 "$GNUPGHOME"
mkdir -p "$out"

export RCLONE_CONFIG_PKGS_TYPE=s3 RCLONE_CONFIG_PKGS_PROVIDER=$provider RCLONE_CONFIG_PKGS_REGION=$region
export RCLONE_CONFIG_PKGS_ENDPOINT="${!endpoint}" RCLONE_CONFIG_PKGS_ACCESS_KEY_ID="${!akid}"
export RCLONE_CONFIG_PKGS_SECRET_ACCESS_KEY="${!secret}"
export RCLONE_CONFIG_PKGS_FORCE_PATH_STYLE=true RCLONE_CONFIG_PKGS_NO_CHECK_BUCKET=true
bucket=${!bucket}
unset PKGS_S3_ACCESS_KEY_ID PKGS_S3_SECRET_ACCESS_KEY PKGS_PUBLIC_ACCESS_KEY_ID PKGS_PUBLIC_SECRET_ACCESS_KEY
rcl() { rclone --config /dev/null --stats 0 "$@"; }

gpg --batch --quiet --import "$root/packaging/keys/bromigos.asc" 2>/dev/null
want=$(gpg --batch --with-colons --list-keys | awk -F: '/^fpr:/ { print $10; exit }')

expect=()
(( now )) || expect=(--expect-version "$version" --expect bromigos bromigos-core bromigos-vector)
deadline=$(( $(date +%s) + 1800 ))
while :; do
  db="$work/$repo.db.tar.gz"
  if ! rcl copyto "pkgs:$bucket/$prefix/$repo.db.tar.gz" "$db" \
     || ! rcl copyto "pkgs:$bucket/$prefix/$repo.db.tar.gz.sig" "$db.sig"; then
    echo "checksums: the $channel channel has no database at $prefix" >&2
    exit 1
  fi
  if ! gpg --batch --quiet --status-fd 1 --verify "$db.sig" "$db" 2>/dev/null | grep -q "VALIDSIG $want "; then
    echo "checksums: the $channel database isn't signed by packaging/keys/bromigos.asc" >&2
    exit 1
  fi
  if python3 "$here/release.py" checksums "$db" "${expect[@]}" > "$out/SHA256SUMS" 2> "$work/why"; then
    break
  fi
  (( $(date +%s) < deadline )) || { cat "$work/why" >&2; exit 1; }
  echo "checksums: waiting for the $channel database: $(cat "$work/why")"
  sleep 30
done
echo "checksums: $(wc -l < "$out/SHA256SUMS") packages in the $channel channel"

if [[ -n "${PKGS_GPG_PRIVATE_KEY:-}" ]]; then
  gpg --batch --quiet --import <<<"$PKGS_GPG_PRIVATE_KEY" 2>/dev/null
  unset PKGS_GPG_PRIVATE_KEY
  fpr=$(gpg --batch --with-colons --list-secret-keys | awk -F: '/^fpr:/ { print $10; exit }')
  [[ "$fpr" == "$want" ]] || { echo "checksums: the signing key isn't packaging/keys/bromigos.asc's" >&2; exit 1; }
  gpg --batch --quiet --yes --pinentry-mode loopback --passphrase-fd 3 --detach-sign --no-armor -u "$fpr" \
    -o "$out/SHA256SUMS.sig" "$out/SHA256SUMS" 3<<<"${PKGS_GPG_PASSPHRASE:-}"
  gpg --batch --quiet --verify "$out/SHA256SUMS.sig" "$out/SHA256SUMS" 2>/dev/null
  echo "checksums: signed as $fpr (SHA256SUMS.sig)"
else
  echo "checksums: PKGS_GPG_PRIVATE_KEY isn't set: SHA256SUMS isn't signed"
fi
