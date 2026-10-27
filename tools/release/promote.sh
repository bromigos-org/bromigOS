#!/usr/bin/env bash
# Promote a release candidate to stable (docs/release.md): vX.Y.Z tagged on the very commits
# vX.Y.Z-rcN tagged, in bromigOS and vector. packages.yml publishes stable from the tag by
# copying the rc channel's signed files (packaging/ci/publish.sh, PKGS_REUSE): nothing is
# rebuilt, and nothing is committed, so the notes are the candidate's. release-promote.yml
# runs it:
#
#   RC=v0.1.2-rc2 DRY_RUN=1 VECTOR_DIR=../vector tools/release/promote.sh
#
# Environment: RC (default: the newest rc tag), DRY_RUN, VECTOR_DIR, OUT, GH_TOKEN,
# VECTOR_GH_TOKEN, PRIVACY_PATTERNS, PKGS_S3_*, PKGS_GPG_*: as in tools/release/cut.sh.
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

git fetch -q --tags origin main
rc=${RC:-$(git tag -l 'v*-rc*' --sort=-version:refname | head -1)}
[[ $rc =~ ^v([0-9]+\.[0-9]+\.[0-9]+)-rc[0-9]+$ ]] || { echo "::error::no release candidate to promote (${rc:-none})"; exit 1; }
version=${BASH_REMATCH[1]} tag=v${BASH_REMATCH[1]}
rc_sha=$(git rev-parse "$rc^{commit}")
echo "release: promote $rc (${rc_sha:0:7}) to $tag"

newest=$(git tag -l "$tag-rc*" --sort=-version:refname | head -1)
[[ $newest == "$rc" ]] || fail "$rc isn't $tag's newest release candidate ($newest is)"
git merge-base --is-ancestor "$rc_sha" origin/main || fail "$rc isn't on main"
# a run that stopped after tagging (e.g. a flaky packages job, re-run since) resumes: the
# tag stays when it's on the candidate's commit, and the rest runs again
tagged() {  # repo-dir: the remote's $tag is on $2's commit (0), elsewhere (fail), or absent (1)
  local at  # the commit an annotated tag points at (its ^{} line sorts last), or a plain tag's
  at=$(git -C "$1" ls-remote --tags origin "refs/tags/$tag" "refs/tags/$tag^{}" | sort -k2 | tail -1 | cut -f1)
  [[ -n $at ]] || return 1
  [[ $at == "$2" ]] || fail "$tag exists in $(basename "$(git -C "$1" rev-parse --show-toplevel)") on ${at:0:7}, not $rc's ${2:0:7}"
}
have_tag=; if tagged . "$rc_sha"; then have_tag=1; echo "release: $tag is on $rc already: resuming"; fi
gh release view "$rc" -R bromigos-org/bromigOS >/dev/null 2>&1 || fail "$rc has no GitHub Release: was it released?"
rel ci-green --repo bromigos-org/bromigOS || fail "bromigOS's main CI isn't green"
rel body --tag "$tag" --ref "$rc" --promoted-from "$rc" > "$out/body.md"
rel body --tag "$tag" --ref "$rc" --promoted-from "$rc" --for vector > "$out/vector-body.md"
rel check "$out/body.md" "$out/vector-body.md" --repos "$root" ${vdir:+"$vdir"} || fail "the notes didn't pass the privacy check"
vrc=
if [[ -n $vdir ]]; then
  git -C "$vdir" fetch -q --tags origin main
  vrc=$(git -C "$vdir" rev-parse -q --verify "refs/tags/$rc^{commit}") || fail "vector has no $rc"
  [[ -z $vrc ]] || git -C "$vdir" merge-base --is-ancestor "$vrc" origin/main || fail "vector's $rc isn't on main"
  have_vtag=; [[ -n $vrc ]] && tagged "$vdir" "$vrc" && have_vtag=1
  GH_TOKEN=$vtoken rel ci-green --repo bromigos-org/vector || fail "vector's main CI isn't green"
else
  fail "no VECTOR checkout: VECTOR is promoted with bromigOS"
fi

if [[ -n $vrc && -z ${have_vtag:-} ]]; then
  act git -C "$vdir" tag -a "$tag" -m "bromigos-vector $version: $rc, promoted to stable" "$vrc"
  act git -C "$vdir" push -q origin "refs/tags/$tag"
fi
if [[ -z $have_tag ]]; then
  act git tag -a "$tag" -m "bromigOS $version: $rc, promoted to stable" "$rc_sha"
  act git push -q origin "refs/tags/$tag"
fi

wait_for() {
  local deadline=$(( $(date +%s) + 7200 )) state=
  while :; do
    state=$(GH_TOKEN=$2 gh run list -R "$1" --workflow packages.yml --branch "$tag" --limit 1 \
              --json status,conclusion --jq '.[0] | "\(.status) \(.conclusion)"' 2>/dev/null || true)
    case $state in
      "completed success") echo "release: $1: $tag published to stable"; return 0 ;;
      completed*) echo "::error::$1: packages.yml for $tag ended ${state#completed }"; return 1 ;;
    esac
    (( $(date +%s) < deadline )) || { echo "::error::$1: packages.yml for $tag didn't end in 2 h"; return 1; }
    sleep 30
  done
}
if [[ $dry ]]; then
  echo "would: wait for packages.yml's $tag runs (stable, the rc's files copied, not rebuilt)"
else
  [[ -n $vrc ]] && wait_for bromigos-org/vector "$vtoken"
  wait_for bromigos-org/bromigOS "${GH_TOKEN:-}"
fi
"$root/tools/release/checksums.sh" stable "$out" ${dry:+--now} "$version"

sig=()
[[ -f $out/SHA256SUMS.sig ]] && sig=("$out/SHA256SUMS.sig")
released() { GH_TOKEN=${2:-${GH_TOKEN:-}} gh release view "$tag" -R "$1" >/dev/null 2>&1; }
released bromigos-org/bromigOS && echo "release: bromigOS's $tag GitHub Release exists" ||
act gh release create "$tag" -R bromigos-org/bromigOS --verify-tag --latest --title "bromigOS $version" \
  --notes-file "$out/body.md" "$out/SHA256SUMS" "${sig[@]}"
if [[ -n $vrc ]] && ! released bromigos-org/vector "$vtoken"; then
  GH_TOKEN=$vtoken act gh release create "$tag" -R bromigos-org/vector --verify-tag --latest \
    --title "VECTOR $version" --notes-file "$out/vector-body.md"
fi
printf 'TAG=%q\nRC=%q\n' "$tag" "$rc" > "$out/result.env"
echo "release: ${dry:+(dry run) }$rc promoted to $tag"
