#!/usr/bin/env bash
# Build the manual (mdBook) and publish it next to the packages, at <bucket>/<repo>/manual/
# (served at https://<host>/bromigos/manual/; homelab helm/bromigos-pkgs). Run by
# .github/workflows/manual.yml with the same bucket credentials as packaging/ci/publish.sh
# (never printed), and to the public mirror when PKGS_PUBLIC_BUCKET is set (packaging/README.md).
# `manual/publish.sh --build-only DIR` just builds.
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
out=$(mktemp -d)
trap 'rm -rf "$out"' EXIT
mdbook build "$here" -d "$out/book"
test -f "$out/book/index.html"
if [[ "${1:-}" == "--build-only" ]]; then cp -r "$out/book" "$2"; echo "manual: built into $2"; exit 0; fi
for v in PKGS_S3_ENDPOINT PKGS_S3_BUCKET PKGS_S3_ACCESS_KEY_ID PKGS_S3_SECRET_ACCESS_KEY; do
  [[ -n "${!v:-}" ]] || { echo "manual: $v is not set" >&2; exit 2; }
done
export RCLONE_CONFIG_PKGS_TYPE=s3 RCLONE_CONFIG_PKGS_PROVIDER=Other RCLONE_CONFIG_PKGS_REGION=us-east-1
export RCLONE_CONFIG_PKGS_ENDPOINT="$PKGS_S3_ENDPOINT" RCLONE_CONFIG_PKGS_ACCESS_KEY_ID="$PKGS_S3_ACCESS_KEY_ID"
export RCLONE_CONFIG_PKGS_SECRET_ACCESS_KEY="$PKGS_S3_SECRET_ACCESS_KEY"
export RCLONE_CONFIG_PKGS_FORCE_PATH_STYLE=true RCLONE_CONFIG_PKGS_NO_CHECK_BUCKET=true
unset PKGS_S3_ACCESS_KEY_ID PKGS_S3_SECRET_ACCESS_KEY
rclone --config /dev/null --stats 0 sync --checksum "$out/book" "pkgs:$PKGS_S3_BUCKET/${PKGS_REPO:-bromigos}/manual"
echo "manual: published $(find "$out/book" -type f | wc -l) files to ${PKGS_REPO:-bromigos}/manual/"
# The public mirror (packaging/README.md, "The public mirror"), when its bucket is set.
if [[ -n "${PKGS_PUBLIC_BUCKET:-}" ]]; then
  export RCLONE_CONFIG_PUB_TYPE=s3 RCLONE_CONFIG_PUB_PROVIDER=Cloudflare RCLONE_CONFIG_PUB_REGION=auto
  export RCLONE_CONFIG_PUB_NO_CHECK_BUCKET=true RCLONE_CONFIG_PUB_ENDPOINT="${PKGS_PUBLIC_ENDPOINT:?}"
  export RCLONE_CONFIG_PUB_ACCESS_KEY_ID="${PKGS_PUBLIC_ACCESS_KEY_ID:?}" RCLONE_CONFIG_PUB_SECRET_ACCESS_KEY="${PKGS_PUBLIC_SECRET_ACCESS_KEY:?}"
  unset PKGS_PUBLIC_ACCESS_KEY_ID PKGS_PUBLIC_SECRET_ACCESS_KEY
  rclone --config /dev/null --stats 0 sync --checksum "$out/book" "pub:$PKGS_PUBLIC_BUCKET/${PKGS_REPO:-bromigos}/manual"
  echo "manual: and to the public mirror"
fi
