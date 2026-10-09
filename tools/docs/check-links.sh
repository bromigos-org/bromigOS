#!/usr/bin/env bash
# Every relative link and #anchor in the repository's Markdown (and in a built manual,
# when given) resolves. lychee, offline: links to the web aren't fetched. CI: docs.yml.
#
#   tools/docs/check-links.sh [BUILT_MANUAL_DIR]
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
mapfile -t md < <(git ls-files '*.md' | grep -v -e '^packaging/[^/]*/\(pkg\|src\)/')
# (mdBook's 404 page links to the site root, which only a web server resolves)
lychee --offline --include-fragments --no-progress --exclude-path '404\.html$' "${md[@]}" ${1:+"$1"}
