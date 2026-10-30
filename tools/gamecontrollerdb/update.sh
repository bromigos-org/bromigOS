#!/bin/sh
# Refresh desktop/lib/gamecontrollerdb.txt from SDL_GameControllerDB: the Linux mappings
# only (bromigos_gamepad reads them), with where they came from at the top.
#   tools/gamecontrollerdb/update.sh
set -eu
repo=https://github.com/mdqinc/SDL_GameControllerDB
root=$(cd "$(dirname "$0")/../.." && pwd)
out="$root/desktop/lib/gamecontrollerdb.txt"
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
commit=$(git ls-remote "$repo" HEAD | cut -c1-12)
curl -fsSL "https://raw.githubusercontent.com/mdqinc/SDL_GameControllerDB/$commit/gamecontrollerdb.txt" -o "$tmp" ||
  curl -fsSL "$repo/raw/master/gamecontrollerdb.txt" -o "$tmp"
{
  echo "# SDL_GameControllerDB, the Linux mappings only: $repo"
  echo "# at commit $commit, fetched $(date -u +%Y-%m-%d). zlib licence: see gamecontrollerdb.LICENSE."
  echo "# Refresh: tools/gamecontrollerdb/update.sh. bromigos_gamepad reads it to name a controller's"
  echo "# sticks, triggers and buttons the way SDL (and so Steam and most games) does."
  grep 'platform:Linux' "$tmp"
} > "$out"
curl -fsSL "https://raw.githubusercontent.com/mdqinc/SDL_GameControllerDB/$commit/LICENSE" \
  -o "$root/desktop/lib/gamecontrollerdb.LICENSE"
echo "$(grep -vc '^#' "$out") mappings from $commit"
