#!/usr/bin/env bash
# Prepare a release (docs/release.md): the version, the notes, the changelog, and the release
# branches and PRs in bromigOS and vector. release-prepare.yml runs it; a dry run by hand is
# the same script:
#
#   BUMP=patch KIND=rc DRY_RUN=1 VECTOR_DIR=../vector tools/release/prepare.sh
#
# It works in this checkout (on main) and VECTOR_DIR's: each gets the release branch,
# checked out, with the release commit on it.
#
# Environment:
#   BUMP, KIND        patch|minor|major|X.Y.Z, and rc|stable
#   DRY_RUN=1         release-dryrun/ branches and draft PRs; guards warn; no model: the commit
#                     subjects stand in for the notes
#   VECTOR_DIR        a checkout of bromigos-org/vector's main (required unless DRY_RUN)
#   PUSH=1            push both release branches and open (or update) the PRs
#   OUT               where plan.json, notes.json and the PR texts go (default: a temp dir)
#   GH_TOKEN          GitHub: CI runs and issues (read); with PUSH, the PRs (write)
#   VECTOR_GH_TOKEN   the same for vector when it's another token (default GH_TOKEN)
#   LITELLM_BASE_URL, LITELLM_API_KEY, PRIVACY_PATTERNS: the model; the lab's own names
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$root"
rel() { python3 -u "$root/tools/release/release.py" "$@"; }
dry=${DRY_RUN:-} vdir=${VECTOR_DIR:-} out=${OUT:-$(mktemp -d)}
vtoken=${VECTOR_GH_TOKEN:-${GH_TOKEN:-}}
mkdir -p "$out"
fail() {
  if [[ $dry ]]; then echo "::warning::$1 (a real run stops here)"; else echo "::error::$1"; exit 1; fi
}
[[ -n $vdir || $dry ]] || fail "VECTOR_DIR isn't set: VECTOR is released with bromigOS"

# Guard: no release from a red main, in either repository.
rel ci-green --repo bromigos-org/bromigOS || fail "bromigOS's main CI is red"
if [[ $vdir ]]; then
  GH_TOKEN=$vtoken rel ci-green --repo bromigos-org/vector || fail "vector's main CI is red"
fi

rel plan --bump "${BUMP:?BUMP}" --kind "${KIND:?KIND}" ${vdir:+--vector "$vdir"} --out "$out/plan.json" >/dev/null
tag=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["tag"])' "$out/plan.json")
branch=$([[ $dry ]] && echo "release-dryrun/$tag" || echo "release/$tag")
echo "release: $tag, on $branch"

GH_TOKEN=${GH_TOKEN:-} rel notes --plan "$out/plan.json" ${vdir:+--vector "$vdir"} ${dry:+--fallback} \
  --out "$out/notes.json"

vcommit=
if [[ $vdir ]]; then
  git -C "$vdir" checkout -q -B "$branch"
  rel write-vector --plan "$out/plan.json" --notes "$out/notes.json" --vector "$vdir"
  git -C "$vdir" add VERSION CHANGELOG.md
  git -C "$vdir" commit -q -m "release: $tag (VERSION, CHANGELOG.md)"
  vcommit=$(git -C "$vdir" rev-parse HEAD)
fi

git checkout -q -B "$branch"
rel write --plan "$out/plan.json" --notes "$out/notes.json" ${vcommit:+--vector-commit "$vcommit" --vector-branch "$branch"}
git add CHANGELOG.md manual/src/whats-new.md core/Cargo.toml core/Cargo.lock tools/release/current.json
git commit -q -m "release: $tag (the notes, CHANGELOG.md, version)"
git --no-pager show --stat --format='release: %h %s' HEAD

# Guard: the generated text passes the privacy check; the manual still builds.
rel pr-body --plan "$out/plan.json" --notes "$out/notes.json" ${dry:+--dry-run} > "$out/pr-body.md"
files=(manual/src/whats-new.md CHANGELOG.md "$out/pr-body.md")
[[ $vdir ]] && files+=("$vdir/CHANGELOG.md")
rel check "${files[@]}" --repos "$root" ${vdir:+"$vdir"}
if command -v mdbook >/dev/null; then
  mdbook build manual -d "$out/book" >/dev/null && test -s "$out/book/whats-new.html"
  echo "release: the manual builds, with the notes"
fi

links=
if [[ ${PUSH:-} ]]; then
  pr() {  # pr REPO BODY-FILE TOKEN: the PR for $branch, opened or updated; prints its URL
    local url
    url=$(GH_TOKEN=$3 gh pr list -R "$1" --head "$branch" --state open --json url --jq '.[0].url // ""')
    if [[ -n $url ]]; then
      GH_TOKEN=$3 gh pr edit "$url" --title "release: $tag" --body-file "$2" >/dev/null
    else
      url=$(GH_TOKEN=$3 gh pr create -R "$1" --base main --head "$branch" --title "release: $tag" \
              --body-file "$2" ${dry:+--draft})
    fi
    echo "$url"
  }
  vector_pr=
  if [[ $vdir ]]; then
    git -C "$vdir" push -q -f origin "$branch"
    rel pr-body --for vector --plan "$out/plan.json" --notes "$out/notes.json" ${dry:+--dry-run} > "$out/vector-pr-body.md"
    vector_pr=$(pr bromigos-org/vector "$out/vector-pr-body.md" "$vtoken")
  fi
  rel pr-body --plan "$out/plan.json" --notes "$out/notes.json" ${vector_pr:+--vector-pr "$vector_pr"} \
    ${dry:+--dry-run} > "$out/pr-body.md"
  rel check "$out/pr-body.md" --repos "$root" ${vdir:+"$vdir"}
  git push -q -f origin "$branch"
  links="$(pr bromigos-org/bromigOS "$out/pr-body.md" "${GH_TOKEN:-}") $vector_pr"
  echo "release: PRs: $links"
fi
printf 'TAG=%q\nBRANCH=%q\nPR_LINKS=%q\n' "$tag" "$branch" "$links" > "$out/result.env"
