#!/usr/bin/env bash
# Cut a prepared release (docs/release.md): the guards, VECTOR's release commit onto its main
# and tagged, bromigOS's tagged (each tag publishes its channel through packages.yml), the
# packages' checksums, both GitHub Releases. release.yml runs it when a release PR is merged;
# a dry run by hand reads a release-dryrun/ branch and changes nothing:
#
#   REF=release-dryrun/v0.1.2 DRY_RUN=1 VECTOR_DIR=../vector tools/release/cut.sh
#
# Environment:
#   RELEASE_SHA       the release commit (a merged PR's head); or REF, a branch or commit to
#                     fetch; neither: the commit on main that last wrote tools/release/current.json
#   MERGED_SHA        main's commit that merged it, whose CI is waited for (default: main)
#   DRY_RUN=1         report the guards instead of stopping; print the tags, pushes and
#                     releases instead of making them; checksums of the channel as it is
#   VECTOR_DIR        a checkout of bromigos-org/vector (main), able to push
#   OUT               where the bodies and SHA256SUMS go (default: a temp dir)
#   GH_TOKEN          bromigOS: CI (read), the GitHub Release (write)
#   VECTOR_GH_TOKEN   vector: CI (read), merges and the GitHub Release (write)
#   PRIVACY_PATTERNS  the lab's own names; PKGS_S3_*, PKGS_GPG_*: tools/release/checksums.sh
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
act() { if [[ $dry ]]; then echo "would: $*"; else "$@"; fi; }

git fetch -q origin main
release=${RELEASE_SHA:-}
if [[ -z $release && -n ${REF:-} ]]; then
  git fetch -q origin "$REF" && release=$(git rev-parse FETCH_HEAD)
fi
[[ -n $release ]] || release=$(git log -1 --format=%H origin/main -- tools/release/current.json)
merged=${MERGED_SHA:-$(git rev-parse origin/main)}
# squash-merged: main's new commit has the release commit's very tree, and stands for it
if ! git merge-base --is-ancestor "$release" origin/main 2>/dev/null && [[ -n ${MERGED_SHA:-} ]] \
   && [[ $(git rev-parse "$merged^{tree}") == $(git rev-parse "$release^{tree}") ]]; then
  release=$merged
fi
git show "$release:tools/release/current.json" > "$out/current.json" \
  || { echo "::error::${release:0:7} prepares no release (no tools/release/current.json)"; exit 1; }
field() { python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); [d := (d or {}).get(k) for k in sys.argv[2:]]; print(d if d is not None else "")' "$out/current.json" "$@"; }
tag=$(field tag) kind=$(field kind) version=$(field version)
vcommit=$(field vector commit) vbase=$(field vector base) vbranch=$(field vector branch)
channel=$([[ $kind == rc ]] && echo rc || echo stable)
[[ -z ${TAG:-} || ${TAG:-} == "$tag" ]] || { echo "::error::${release:0:7} prepares $tag, not $TAG"; exit 1; }
echo "release: $tag ($kind): bromigOS ${release:0:7}, VECTOR ${vcommit:0:7}, main at ${merged:0:7}, the $channel channel"

# ------------------------------------------------------------------ guards
git merge-base --is-ancestor "$release" origin/main || fail "the release commit ${release:0:7} isn't on main"
# a tag that exists already must be this release's own (a run that stopped after tagging is
# resumed: the publish is waited for, the sums and the GitHub Releases are made); any other
# commit under the tag is a version tagged twice
tagged_at() { git ${1:+-C "$1"} ls-remote --tags origin "refs/tags/$tag^{}" | cut -f1; }
btag=$(tagged_at)
[[ -z $btag || $btag == "$release" ]] || fail "$tag exists in bromigOS already, on ${btag:0:7}, not ${release:0:7}"
[[ -n $btag ]] && echo "release: $tag is on ${release:0:7} already: resuming"
[[ $(git show "$release:core/Cargo.toml" | sed -n '/^\[workspace\.package\]/,/^\[/ s/^version *= *"\(.*\)"/\1/p') == "$version" ]] \
  || fail "core/Cargo.toml at ${release:0:7} isn't version $version"
wait=()
[[ $dry ]] || wait=(--wait-sha "$merged")     # the merge's own runs, to their end, first
rel ci-green --repo bromigos-org/bromigOS "${wait[@]}" || fail "bromigOS's main CI isn't green"
rel body --tag "$tag" --ref "$release" > "$out/body.md"
rel body --tag "$tag" --ref "$release" --for vector > "$out/vector-body.md"
rel check "$out/body.md" "$out/vector-body.md" --repos "$root" ${vdir:+"$vdir"} || fail "the notes didn't pass the privacy check"
if [[ -z $vdir || -z $vcommit ]]; then
  fail "no VECTOR checkout or release commit: VECTOR is tagged with bromigOS"
else
  git -C "$vdir" fetch -q origin main
  if git -C "$vdir" fetch -q origin "$vbranch" 2>/dev/null; then
    [[ $(git -C "$vdir" rev-parse FETCH_HEAD) == "$vcommit" ]] || fail "vector's $vbranch isn't ${vcommit:0:7}, the commit the PR names"
  else
    git -C "$vdir" merge-base --is-ancestor "$vcommit" origin/main 2>/dev/null || fail "vector has neither $vbranch nor ${vcommit:0:7} on main"
  fi
  [[ $(git -C "$vdir" rev-parse "$vcommit^" 2>/dev/null) == "$vbase" ]] \
    || fail "VECTOR's release commit isn't on ${vbase:0:7}, where its notes were drafted"
  vtag=$(tagged_at "$vdir")
  [[ -z $vtag || $vtag == "$vcommit" ]] || fail "$tag exists in vector already, on ${vtag:0:7}, not ${vcommit:0:7}"
  GH_TOKEN=$vtoken rel ci-green --repo bromigos-org/vector || fail "vector's main CI isn't green"
fi

# ------------------------------------------------------------------ VECTOR, then bromigOS
# VECTOR's release commit onto its main: a fast-forward (never forced), or a merge commit
# when vector's main moved on since; then its tag. Each tag starts that repository's
# packages.yml, which publishes the channel the tag names.
if [[ -n $vdir && -n $vcommit ]]; then
  if git -C "$vdir" merge-base --is-ancestor "$vcommit" origin/main; then
    echo "release: vector: ${vcommit:0:7} is on main already"
  elif git -C "$vdir" merge-base --is-ancestor origin/main "$vcommit"; then
    act git -C "$vdir" push -q origin "$vcommit:refs/heads/main"
  else
    GH_TOKEN=$vtoken act gh api -X POST repos/bromigos-org/vector/merges -f base=main -f head="$vbranch" \
      -f commit_message="release: $tag: merge $vbranch" --jq .sha
  fi
  if [[ -z $vtag ]]; then
    act git -C "$vdir" tag -a "$tag" -m "bromigos-vector ${tag#v}: released with bromigOS ${tag#v}" "$vcommit"
    act git -C "$vdir" push -q origin "refs/tags/$tag"
  fi
fi
if [[ -z $btag ]]; then
  act git tag -a "$tag" -m "bromigOS ${tag#v}: the notes are the GitHub Release's and manual/src/whats-new.md" "$release"
  act git push -q origin "refs/tags/$tag"
fi

# ------------------------------------------------------------------ the publish, the sums
wait_for() {  # wait_for REPO TOKEN: packages.yml's run for $tag, to its end
  local deadline=$(( $(date +%s) + 7200 )) state=
  while :; do
    state=$(GH_TOKEN=$2 gh run list -R "$1" --workflow packages.yml --branch "$tag" --limit 1 \
              --json status,conclusion --jq '.[0] | "\(.status) \(.conclusion)"' 2>/dev/null || true)
    case $state in
      "completed success") echo "release: $1: $tag published to $channel"; return 0 ;;
      completed*) echo "::error::$1: packages.yml for $tag ended ${state#completed }"; return 1 ;;
    esac
    (( $(date +%s) < deadline )) || { echo "::error::$1: packages.yml for $tag didn't end in 2 h"; return 1; }
    sleep 30
  done
}
if [[ $dry ]]; then
  echo "would: wait for packages.yml's $tag runs in vector and bromigOS (the $channel channel)"
else
  [[ -n $vdir ]] && wait_for bromigos-org/vector "$vtoken"
  wait_for bromigos-org/bromigOS "${GH_TOKEN:-}"
fi
"$root/tools/release/checksums.sh" "$channel" "$out" ${dry:+--now} "$version"

# ------------------------------------------------------------------ GitHub Releases
flag=$([[ $kind == rc ]] && echo --prerelease || echo --latest)
sig=()
[[ -f $out/SHA256SUMS.sig ]] && sig=("$out/SHA256SUMS.sig")
gh release view "$tag" -R bromigos-org/bromigOS >/dev/null 2>&1 && echo "release: bromigOS's GitHub Release for $tag exists" || \
act gh release create "$tag" -R bromigos-org/bromigOS --verify-tag "$flag" --title "bromigOS ${tag#v}" \
  --notes-file "$out/body.md" "$out/SHA256SUMS" "${sig[@]}"
if [[ -n $vdir ]]; then
  GH_TOKEN=$vtoken gh release view "$tag" -R bromigos-org/vector >/dev/null 2>&1 && echo "release: vector's GitHub Release for $tag exists" || \
  GH_TOKEN=$vtoken act gh release create "$tag" -R bromigos-org/vector --verify-tag "$flag" \
    --title "VECTOR ${tag#v}" --notes-file "$out/vector-body.md"
fi
printf 'TAG=%q\nCHANNEL=%q\nRELEASE_SHA=%q\nVECTOR_COMMIT=%q\n' "$tag" "$channel" "$release" "$vcommit" > "$out/result.env"
echo "release: ${dry:+(dry run) }$tag done"
