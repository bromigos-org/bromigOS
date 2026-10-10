#!/usr/bin/env bash
# Make bromigOS's package repository public: the one step that ends early access for the
# packages (docs/public.md). Without --yes it changes nothing: it checks everything it can
# and prints each command it would run.
#
#   tools/release/go-public.sh            check, and print the plan
#   tools/release/go-public.sh --yes      do it
#   tools/release/go-public.sh --private [--yes]
#                                         undo the bucket part: private again
#
# Going public, in order:
#   1. the bucket gs://bromigos-pkgs becomes readable by anyone (objects only, no listing);
#   2. anonymous downloads are checked: install.sh, the key, and every channel's database
#      against its signature. A failure stops here, before any repository changes;
#   3. bromigOS's prepared branch (go-public: install.sh's default repository and the docs)
#      lands on main;
#   4. bromigos.org's prepared branch (os-get-public: /os/get's install steps) lands on
#      main, which deploys the site;
#   5. with GO_PUBLIC_VAULT_PATH set, the bucket's record in Vault says it's public.
# Run it from a bromigOS checkout, signed in to gcloud as an owner of the bromigos-org
# project, and to GitHub (git over SSH) with push access to both repositories. It never
# changes gcloud's default project. The repositories themselves stay private.
set -euo pipefail

PROJECT=${GO_PUBLIC_PROJECT:-bromigos-org}
BUCKET=${GO_PUBLIC_BUCKET:-bromigos-pkgs}
URL=${GO_PUBLIC_URL:-https://storage.googleapis.com/$BUCKET}
OS_REPO=${GO_PUBLIC_OS_REPO:-bromigos-org/bromigOS}
OS_BRANCH=${GO_PUBLIC_OS_BRANCH:-go-public}
SITE_REPO=${GO_PUBLIC_SITE_REPO:-bromigos-org/bromigos.org}
SITE_BRANCH=${GO_PUBLIC_SITE_BRANCH:-os-get-public}
VAULT_PATH=${GO_PUBLIC_VAULT_PATH:-}   # the secret-store record of the bucket, if any
GIT_BASE=${GO_PUBLIC_GIT_BASE:-git@github.com:}
REPO=bromigos
CHANNELS=("edge:$REPO/x86_64" "rc:$REPO/rc/x86_64" "stable:$REPO/stable/x86_64")
ROLE=roles/storage.legacyObjectReader   # read objects; no bucket listing

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root=$(cd "$here/../.." && pwd)
FPR=${GO_PUBLIC_FPR:-$(sed -n 's/^FPR=\([0-9A-F]\{40\}\)$/\1/p' "$root/install.sh")}

yes=0 private=0
for a in "$@"; do
  case $a in
    --yes) yes=1 ;;
    --private) private=1 ;;
    -h|--help) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "go-public: unknown option $a (--yes, --private)" >&2; exit 2 ;;
  esac
done

say() { printf 'go-public: %s\n' "$*"; }
die() { printf 'go-public: %s\n' "$*" >&2; exit 1; }
# run CMD...: do it with --yes; otherwise only print it.
run() {
  if ((yes)); then say "run: $*"; "$@"; else say "would run: $*"; fi
}
G=(gcloud --project "$PROJECT" --billing-project="$PROJECT")   # never gcloud's default project
gc() { "${G[@]}" "$@"; }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
export GNUPGHOME="$tmp/gnupg"
mkdir -m 700 "$GNUPGHOME"

for t in gcloud git curl gpg tar; do
  command -v "$t" >/dev/null || die "needs $t"
done
[[ -n $FPR ]] || die "can't read the key's fingerprint (FPR=) from install.sh"
((yes)) || say "dry run: nothing changes. Add --yes to do it."

# ── Undo: private again ──────────────────────────────────────────────────────
if ((private)); then
  say "making gs://$BUCKET private again"
  run "${G[@]}" storage buckets remove-iam-policy-binding "gs://$BUCKET" --member=allUsers --role="$ROLE"
  run "${G[@]}" storage buckets update "gs://$BUCKET" --public-access-prevention
  say "the repositories and the site keep their go-public commits; revert those by hand if needed"
  exit 0
fi

# ── Checks (read-only, every run) ────────────────────────────────────────────
say "1/5 checks"
pap=$(gc storage buckets describe "gs://$BUCKET" --format='value(public_access_prevention)') \
  || die "can't read gs://$BUCKET in $PROJECT (signed in to gcloud as an owner?)"
members=$(gc storage buckets get-iam-policy "gs://$BUCKET" --format=json)
if grep -q '"allUsers"' <<<"$members"; then
  say "  gs://$BUCKET already grants allUsers: the bucket is public"
  already=1
else
  say "  gs://$BUCKET is private (public access prevention: ${pap:-unset})"
  already=0
fi

# The mirror holds every channel, each database with a valid signature.
gc storage cat "gs://$BUCKET/$REPO/bromigos.asc" > "$tmp/bromigos.asc" \
  || die "gs://$BUCKET/$REPO/bromigos.asc is missing: has CI published to the mirror? (docs/public.md)"
got=$(gpg --batch --with-colons --import-options show-only --import "$tmp/bromigos.asc" 2>/dev/null | awk -F: '/^fpr:/ { print $10; exit }')
[[ $got == "$FPR" ]] || die "the mirror's key is ${got:-unreadable}, not install.sh's $FPR"
gpg --batch --quiet --import "$tmp/bromigos.asc" 2>/dev/null
say "  the mirror's signing key is $FPR, the one install.sh pins"
gc storage cat "gs://$BUCKET/$REPO/install.sh" > "$tmp/install.sh" || die "gs://$BUCKET/$REPO/install.sh is missing"
for c in "${CHANNELS[@]}"; do
  name=${c%%:*} prefix=${c#*:}
  gc storage cat "gs://$BUCKET/$prefix/$REPO.db" > "$tmp/$name.db" 2>/dev/null \
    || die "the $name channel isn't on the mirror (gs://$BUCKET/$prefix/$REPO.db); run packages.yml with mirror_only (docs/public.md)"
  gc storage cat "gs://$BUCKET/$prefix/$REPO.db.sig" > "$tmp/$name.db.sig" || die "gs://$BUCKET/$prefix/$REPO.db.sig is missing"
  gpg --batch --quiet --verify "$tmp/$name.db.sig" "$tmp/$name.db" 2>/dev/null \
    || die "the $name channel's database on the mirror doesn't match its signature"
  n=$(tar -tzf "$tmp/$name.db" 2>/dev/null | grep -c '/desc$' || true)
  say "  $name: $n packages, database signed by $FPR"
done
# Public means anyone may download every package, so name the ones under a proprietary
# licence: their terms must allow redistribution (docs/public.md, "Before you go public").
tar -xzOf "$tmp/edge.db" --wildcards '*/desc' 2>/dev/null \
  | awk '/^%NAME%$/ { getline; n = $0 } /^%LICENSE%$/ { getline; if ($0 ~ /^LicenseRef-/) print n " (" $0 ")" }' \
  | sort -u | while read -r p; do say "  note: $p is proprietary: check that its licence allows a public mirror"; done

# The prepared branches exist and land on today's main without conflicts.
for r in "$OS_REPO:$OS_BRANCH" "$SITE_REPO:$SITE_BRANCH"; do
  repo=${r%%:*} branch=${r#*:} dir="$tmp/$(basename "$repo")"
  git clone --quiet --filter=blob:none --no-checkout "$GIT_BASE$repo.git" "$dir" \
    || die "can't clone $repo (signed in to GitHub?)"
  git -C "$dir" rev-parse --verify --quiet "origin/$branch" >/dev/null \
    || die "$repo has no $branch branch: the change it prepares is missing (docs/public.md)"
  ahead=$(git -C "$dir" rev-list --count "origin/main..origin/$branch")
  git -C "$dir" merge-tree --write-tree origin/main "origin/$branch" >/dev/null \
    || die "$repo's $branch conflicts with main: rebase it first (docs/public.md)"
  say "  $repo: $branch is $ahead commit(s) on top of main's history, and merges cleanly"
done
pinned=$(git -C "$tmp/${OS_REPO##*/}" show "origin/$OS_BRANCH:install.sh" | sed -n "s/^PUBLIC_REPO='\{0,1\}\([^' ]*\).*/\1/p")
[[ $pinned == "$URL" ]] || die "$OS_REPO's $OS_BRANCH sets install.sh's PUBLIC_REPO to '${pinned}', not $URL"
say "  install.sh on $OS_BRANCH defaults to $URL"

say "  cost once public: downloads leave Google Cloud at about \$0.12 per GB. An install"
say "  fetches about 0.1 GB of bromigOS packages (1password adds 0.2 GB), so about \$0.01-0.04"
say "  each; storage is about \$0.026 per GB a month. Watch it: Billing, bromigos-org"

# ── 2. The bucket, readable by anyone ────────────────────────────────────────
say "2/5 the bucket: anyone may read its objects"
if ((already)); then
  say "  already done"
else
  run "${G[@]}" storage buckets update "gs://$BUCKET" --no-public-access-prevention
  run "${G[@]}" storage buckets add-iam-policy-binding "gs://$BUCKET" --member=allUsers --role="$ROLE"
fi

# ── 3. Check it as a stranger would: no credentials ──────────────────────────
say "3/5 anonymous downloads"
if ((yes)); then
  ok=0
  for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do      # IAM changes take up to a minute
    if curl -fsS -o "$tmp/anon.asc" "$URL/$REPO/bromigos.asc" 2>/dev/null; then ok=1; break; fi
    sleep 10
  done
  ((ok)) || die "$URL/$REPO/bromigos.asc still isn't readable; nothing else was changed. Undo: $0 --private --yes"
  cmp -s "$tmp/anon.asc" "$tmp/bromigos.asc" || die "the key anyone downloads differs from the mirror's"
  curl -fsS -o "$tmp/anon.sh" "$URL/$REPO/install.sh" || die "$URL/$REPO/install.sh isn't readable"
  for c in "${CHANNELS[@]}"; do
    name=${c%%:*} prefix=${c#*:}
    curl -fsS -o "$tmp/anon.db" "$URL/$prefix/$REPO.db" && curl -fsS -o "$tmp/anon.db.sig" "$URL/$prefix/$REPO.db.sig" \
      && gpg --batch --quiet --verify "$tmp/anon.db.sig" "$tmp/anon.db" 2>/dev/null \
      || die "$name: the anonymous database doesn't verify. Undo: $0 --private --yes"
    say "  $name: $URL/$prefix/$REPO.db verifies"
  done
else
  say "  would fetch, with no credentials, and verify against $FPR:"
  say "    $URL/$REPO/install.sh and $URL/$REPO/bromigos.asc"
  for c in "${CHANNELS[@]}"; do say "    $URL/${c#*:}/$REPO.db and .sig"; done
fi

# ── 4. The prepared branches land on main ───────────────────────────────────
say "4/5 the prepared changes land on main"
land() {   # land REPO BRANCH: rebase BRANCH on main and push it as main, then drop the branch
  local repo=$1 branch=$2 dir
  dir="$tmp/${1##*/}"
  if ((yes)); then
    git -C "$dir" checkout --quiet -B "$branch" "origin/$branch"
    git -C "$dir" rebase --quiet origin/main || die "$repo: $branch doesn't rebase onto main; nothing pushed there"
    run git -C "$dir" push --quiet origin "HEAD:main"
    run git -C "$dir" push --quiet origin --delete "$branch"
  else
    say "would run: git -C <clone of $repo> rebase origin/main  (on $branch)"
    say "would run: git -C <clone of $repo> push origin HEAD:main"
    say "would run: git -C <clone of $repo> push origin --delete $branch"
  fi
}
land "$OS_REPO" "$OS_BRANCH"
say "  bromigOS: install.sh defaults to $URL; the next publish copies it to both buckets"
land "$SITE_REPO" "$SITE_BRANCH"
say "  bromigos.org: /os/get shows the install steps once its deploy finishes"

# ── 5. Vault's record ────────────────────────────────────────────────────────
say "5/5 the bucket's record in Vault"
if [[ -z $VAULT_PATH ]]; then
  say "  GO_PUBLIC_VAULT_PATH isn't set: skipped"
elif command -v vault >/dev/null; then
  run vault kv patch "$VAULT_PATH" status="public since $(date -u +%Y-%m-%dT%H:%MZ); undo: tools/release/go-public.sh --private --yes"
else
  say "  vault isn't installed here: mark $VAULT_PATH public by hand"
fi

if ((yes)); then
  say "bromigOS's packages are public at $URL"
else
  say "dry run done: every check passed. Run it again with --yes to go public."
fi
