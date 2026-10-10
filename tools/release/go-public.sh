#!/usr/bin/env bash
# Make bromigOS's package repository public: the one step that ends early access for the
# packages (docs/public.md). Without --yes it changes nothing: it checks everything it can
# and prints each change it would make.
#
#   tools/release/go-public.sh [--domain HOST]          check, and print the plan
#   tools/release/go-public.sh [--domain HOST] --yes    do it
#   tools/release/go-public.sh --private [--domain HOST] [--yes]
#                                                       undo the bucket part: private again
#
# The bucket is the Cloudflare R2 bucket bromigos-pkgs. It goes public at its r2.dev
# address, or with --domain at a custom domain (pkgs.bromigos.org) in a Cloudflare zone.
# Going public, in order:
#   1. checks: the bucket, the key, every channel's signed database (read with the mirror's
#      S3 key), and the two prepared branches;
#   2. the bucket's public address is turned on;
#   3. anonymous downloads are checked: install.sh, the key, and every channel's database
#      against its signature. A failure stops here, before any repository changes;
#   4. bromigOS's prepared branch (go-public: install.sh's default repository and the docs)
#      and bromigos.org's (os-get-public: /os/get's install steps) land on main. With
#      --domain, the r2.dev address they carry becomes the custom one first;
#   5. with GO_PUBLIC_VAULT_PATH set, the bucket's record in Vault says it's public.
#
# Credentials, from the environment, never printed:
#   CLOUDFLARE_API_TOKEN       a token that may edit R2 (and read the zone, for --domain)
#   CF_ACCOUNT_ID              the Cloudflare account
#   PKGS_PUBLIC_ACCESS_KEY_ID, PKGS_PUBLIC_SECRET_ACCESS_KEY    the mirror's S3 key
# or GO_PUBLIC_VAULT_PATH, the bucket's record in Vault: account_id, access_key, secret_key,
# and cloudflare_token_path + cloudflare_token_field naming where the API token is.
# Run it from a bromigOS checkout, signed in to GitHub (git over SSH) with push access to
# both repositories. The repositories themselves stay private.
set -euo pipefail

BUCKET=${GO_PUBLIC_BUCKET:-bromigos-pkgs}
OS_REPO=${GO_PUBLIC_OS_REPO:-bromigos-org/bromigOS}
OS_BRANCH=${GO_PUBLIC_OS_BRANCH:-go-public}
SITE_REPO=${GO_PUBLIC_SITE_REPO:-bromigos-org/bromigos.org}
SITE_BRANCH=${GO_PUBLIC_SITE_BRANCH:-os-get-public}
VAULT_PATH=${GO_PUBLIC_VAULT_PATH:-}
GIT_BASE=${GO_PUBLIC_GIT_BASE:-git@github.com:}
API=${GO_PUBLIC_CF_API:-https://api.cloudflare.com/client/v4}
REPO=bromigos
CHANNELS=("edge:$REPO/x86_64" "rc:$REPO/rc/x86_64" "stable:$REPO/stable/x86_64")

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root=$(cd "$here/../.." && pwd)
FPR=${GO_PUBLIC_FPR:-$(sed -n 's/^FPR=\([0-9A-F]\{40\}\)$/\1/p' "$root/install.sh")}

yes=0 private=0 domain=''
while (($#)); do
  case $1 in
    --yes) yes=1; shift ;;
    --private) private=1; shift ;;
    --domain) domain=${2:?--domain needs a host name}; shift 2 ;;
    -h|--help) sed -n '2,31p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "go-public: unknown option $1 (--yes, --domain HOST, --private)" >&2; exit 2 ;;
  esac
done

say() { printf 'go-public: %s\n' "$*"; }
die() { printf 'go-public: %s\n' "$*" >&2; exit 1; }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
umask 077
export GNUPGHOME="$tmp/gnupg"
mkdir -m 700 "$GNUPGHOME"

for t in curl jq git gpg tar sha256sum; do
  command -v "$t" >/dev/null || die "needs $t"
done
[[ -n $FPR ]] || die "can't read the key's fingerprint (FPR=) from install.sh"

# ── Credentials ──────────────────────────────────────────────────────────────
if [[ -n $VAULT_PATH ]]; then
  command -v vault >/dev/null || die "GO_PUBLIC_VAULT_PATH is set but vault isn't installed"
  vault kv get -format=json "$VAULT_PATH" | jq '.data.data' > "$tmp/record.json" || die "can't read $VAULT_PATH from Vault"
  field() { jq -r --arg k "$1" '.[$k] // empty' "$tmp/record.json"; }
  CF_ACCOUNT_ID=${CF_ACCOUNT_ID:-$(field account_id)}
  PKGS_PUBLIC_ACCESS_KEY_ID=${PKGS_PUBLIC_ACCESS_KEY_ID:-$(field access_key)}
  PKGS_PUBLIC_SECRET_ACCESS_KEY=${PKGS_PUBLIC_SECRET_ACCESS_KEY:-$(field secret_key)}
  if [[ -z ${CLOUDFLARE_API_TOKEN:-} && -n $(field cloudflare_token_path) ]]; then
    CLOUDFLARE_API_TOKEN=$(vault kv get -field="$(field cloudflare_token_field)" "$(field cloudflare_token_path)")
  fi
fi
for v in CLOUDFLARE_API_TOKEN CF_ACCOUNT_ID PKGS_PUBLIC_ACCESS_KEY_ID PKGS_PUBLIC_SECRET_ACCESS_KEY; do
  [[ -n ${!v:-} ]] || die "$v isn't set (or set GO_PUBLIC_VAULT_PATH; see the header)"
done
# Kept in files curl reads, never on a command line.
printf 'header = "Authorization: Bearer %s"\n' "$CLOUDFLARE_API_TOKEN" > "$tmp/cf.curl"
printf 'user = "%s:%s"\n' "$PKGS_PUBLIC_ACCESS_KEY_ID" "$PKGS_PUBLIC_SECRET_ACCESS_KEY" > "$tmp/s3.curl"
unset CLOUDFLARE_API_TOKEN PKGS_PUBLIC_ACCESS_KEY_ID PKGS_PUBLIC_SECRET_ACCESS_KEY
S3=${GO_PUBLIC_S3_ENDPOINT:-https://$CF_ACCOUNT_ID.r2.cloudflarestorage.com}
B="$API/accounts/$CF_ACCOUNT_ID/r2/buckets/$BUCKET"

# api METHOD URL [JSON]: a Cloudflare API call; prints its result, stops on success=false.
api() {
  local out
  out=$(curl -sS -K "$tmp/cf.curl" -X "$1" -H 'Content-Type: application/json' ${3:+--data "$3"} "$2") \
    || die "Cloudflare API: $1 ${2#"$API"} didn't answer"
  jq -e '.success' >/dev/null <<<"$out" \
    || die "Cloudflare API: $1 ${2#"$API"}: $(jq -c '.errors' <<<"$out" 2>/dev/null || echo "$out")"
  jq -c '.result' <<<"$out"
}
# change METHOD URL [JSON]: an API call that changes something, made only with --yes.
change() {
  if ((yes)); then say "run: $1 ${2#"$API"} ${3:-}"; api "$@" >/dev/null
  else say "would run: $1 ${2#"$API"} ${3:-}"; fi
}
s3get() { curl -fsS -K "$tmp/s3.curl" --aws-sigv4 "aws:amz:auto:s3" -o "$2" "$S3/$BUCKET/$1"; }

((yes)) || say "dry run: nothing changes. Add --yes to do it."

# ── The bucket's addresses ───────────────────────────────────────────────────
managed=$(api GET "$B/domains/managed")
r2dev=$(jq -r '.domain // empty' <<<"$managed")
[[ -n $r2dev ]] || die "R2 gave no r2.dev address for $BUCKET"
R2DEV_URL="https://$r2dev"
if [[ -n $domain ]]; then
  URL="https://$domain"
  apex=$(awk -F. '{ print $(NF-1) "." $NF }' <<<"$domain")
  zone=$(api GET "$API/zones?name=$apex" | jq -r '.[0].id // empty')
  [[ -n $zone ]] || die "$apex isn't a zone in this Cloudflare account: a custom domain needs its DNS on Cloudflare (docs/public.md)"
  public_now=$(api GET "$B/domains/custom" | jq -r --arg d "$domain" '.domains[]? | select(.domain == $d and .enabled) | .domain')
else
  URL=$R2DEV_URL
  public_now=$(jq -r 'select(.enabled) | .domain' <<<"$managed")
fi

# ── Undo: private again ──────────────────────────────────────────────────────
if ((private)); then
  say "making $BUCKET private again"
  if [[ -n $domain ]]; then change DELETE "$B/domains/custom/$domain"
  else change PUT "$B/domains/managed" '{"enabled":false}'; fi
  say "the repositories and the site keep their go-public commits; revert those by hand if needed"
  exit 0
fi

# ── 1. Checks (read-only, every run) ─────────────────────────────────────────
say "1/5 checks"
if [[ -n $public_now ]]; then say "  $BUCKET is already public at $URL"; else say "  $BUCKET is private; it will be public at $URL"; fi

s3get "$REPO/bromigos.asc" "$tmp/bromigos.asc" \
  || die "$REPO/bromigos.asc isn't in $BUCKET: has CI published to the mirror? (docs/public.md)"
got=$(gpg --batch --with-colons --import-options show-only --import "$tmp/bromigos.asc" 2>/dev/null | awk -F: '/^fpr:/ { print $10; exit }')
[[ $got == "$FPR" ]] || die "the mirror's key is ${got:-unreadable}, not install.sh's $FPR"
gpg --batch --quiet --import "$tmp/bromigos.asc" 2>/dev/null
say "  the mirror's signing key is $FPR, the one install.sh pins"
s3get "$REPO/install.sh" "$tmp/install.sh" || die "$REPO/install.sh isn't in $BUCKET"
for c in "${CHANNELS[@]}"; do
  name=${c%%:*} prefix=${c#*:}
  s3get "$prefix/$REPO.db" "$tmp/$name.db" 2>/dev/null \
    || die "the $name channel isn't on the mirror ($prefix/$REPO.db); run packages.yml with mirror_only (docs/public.md)"
  s3get "$prefix/$REPO.db.sig" "$tmp/$name.db.sig" || die "$prefix/$REPO.db.sig isn't in $BUCKET"
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

# The prepared branches exist, carry the r2.dev address, and land on today's main.
for r in "$OS_REPO:$OS_BRANCH" "$SITE_REPO:$SITE_BRANCH"; do
  repo=${r%%:*} branch=${r#*:}
  dir="$tmp/${repo##*/}"
  git clone --quiet --filter=blob:none --no-checkout "$GIT_BASE$repo.git" "$dir" 2>/dev/null \
    || die "can't clone $repo (signed in to GitHub?)"
  git -C "$dir" rev-parse --verify --quiet "origin/$branch" >/dev/null \
    || die "$repo has no $branch branch: the change it prepares is missing (docs/public.md)"
  ahead=$(git -C "$dir" rev-list --count "origin/main..origin/$branch")
  git -C "$dir" merge-tree --write-tree origin/main "origin/$branch" >/dev/null \
    || die "$repo's $branch conflicts with main: rebase it first (docs/public.md)"
  git -C "$dir" diff "origin/main...origin/$branch" | grep -qF "$R2DEV_URL" \
    || die "$repo's $branch doesn't mention $R2DEV_URL, the bucket's address (docs/public.md)"
  say "  $repo: $branch is $ahead commit(s) on main's history, and merges cleanly"
done
pinned=$(git -C "$tmp/${OS_REPO##*/}" show "origin/$OS_BRANCH:install.sh" | sed -n "s/^PUBLIC_REPO='\{0,1\}\([^' ]*\).*/\1/p")
[[ $pinned == "$R2DEV_URL" ]] || die "$OS_REPO's $OS_BRANCH sets install.sh's PUBLIC_REPO to '$pinned', not $R2DEV_URL"
[[ -z $domain ]] || say "  on landing, $R2DEV_URL becomes $URL in both branches"

say "  cost once public: R2 charges nothing for downloads. Storage is \$0.015 per GB a month"
say "  after the first 10 GB, and reads \$0.36 per million after the first 10 million a month"
[[ -n $domain ]] || say "  note: Cloudflare rate-limits r2.dev addresses and doesn't cache them; a custom domain has neither limit"

# ── 2. The public address ────────────────────────────────────────────────────
say "2/5 the bucket's public address: $URL"
if [[ -n $public_now ]]; then
  say "  already on"
elif [[ -n $domain ]]; then
  change POST "$B/domains/custom" "{\"domain\":\"$domain\",\"zoneId\":\"$zone\",\"enabled\":true,\"minTLS\":\"1.2\"}"
else
  change PUT "$B/domains/managed" '{"enabled":true}'
fi

# ── 3. Check it as a stranger would: no credentials ──────────────────────────
say "3/5 anonymous downloads"
if ((yes)); then
  ok=0
  for _ in $(seq "${GO_PUBLIC_TRIES:-60}"); do   # r2.dev answers in seconds; a custom domain's certificate can take minutes
    if curl -fsS -o "$tmp/anon.asc" "$URL/$REPO/bromigos.asc" 2>/dev/null; then ok=1; break; fi
    sleep "${GO_PUBLIC_WAIT:-10}"
  done
  ((ok)) || die "$URL/$REPO/bromigos.asc still isn't readable; nothing else was changed. Undo: $0 --private${domain:+ --domain $domain} --yes"
  [[ $(sha256sum <"$tmp/anon.asc") == "$(sha256sum <"$tmp/bromigos.asc")" ]] || die "the key anyone downloads differs from the mirror's"
  curl -fsS -o "$tmp/anon.sh" "$URL/$REPO/install.sh" || die "$URL/$REPO/install.sh isn't readable"
  for c in "${CHANNELS[@]}"; do
    name=${c%%:*} prefix=${c#*:}
    curl -fsS -o "$tmp/anon.db" "$URL/$prefix/$REPO.db" && curl -fsS -o "$tmp/anon.db.sig" "$URL/$prefix/$REPO.db.sig" \
      && gpg --batch --quiet --verify "$tmp/anon.db.sig" "$tmp/anon.db" 2>/dev/null \
      || die "$name: the anonymous database doesn't verify. Undo: $0 --private${domain:+ --domain $domain} --yes"
    say "  $name: $URL/$prefix/$REPO.db verifies"
  done
else
  say "  would fetch, with no credentials, and verify against $FPR:"
  say "    $URL/$REPO/install.sh and $URL/$REPO/bromigos.asc"
  for c in "${CHANNELS[@]}"; do say "    $URL/${c#*:}/$REPO.db and .sig"; done
fi

# ── 4. The prepared branches land on main ───────────────────────────────────
say "4/5 the prepared changes land on main"
land() {   # land REPO BRANCH: rebase BRANCH on main, swap in the address, push it as main
  local repo=$1 branch=$2 dir f
  dir="$tmp/${1##*/}"
  if ((yes)); then
    git -C "$dir" checkout --quiet -B "$branch" "origin/$branch"
    git -C "$dir" rebase --quiet origin/main || die "$repo: $branch doesn't rebase onto main; nothing pushed there"
    if [[ $URL != "$R2DEV_URL" ]]; then
      git -C "$dir" diff --name-only origin/main HEAD | while read -r f; do
        if [[ -f $dir/$f ]]; then sed -i "s|$R2DEV_URL|$URL|g" "$dir/$f"; fi
      done
      git -C "$dir" commit --quiet -am "packages: the public repository is $URL"
    fi
    say "run: git push $repo HEAD:main, then delete $branch"
    git -C "$dir" push --quiet origin "HEAD:main"
    git -C "$dir" push --quiet origin --delete "$branch"
  else
    say "would run: git rebase origin/main  (on $repo's $branch)"
    [[ $URL == "$R2DEV_URL" ]] || say "would run: sed s|$R2DEV_URL|$URL| on the files $branch changes, and commit"
    say "would run: git push $repo HEAD:main, then delete $branch"
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
elif ((yes)); then
  vault kv patch "$VAULT_PATH" public_url="$URL" status="public since $(date -u +%Y-%m-%dT%H:%MZ); undo: tools/release/go-public.sh --private${domain:+ --domain $domain} --yes" >/dev/null
  say "  marked public at $URL"
else
  say "  would mark $VAULT_PATH public at $URL"
fi

if ((yes)); then
  say "bromigOS's packages are public at $URL"
else
  say "dry run done: every check passed. Run it again with --yes to go public."
fi
