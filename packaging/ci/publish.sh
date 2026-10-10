#!/usr/bin/env bash
# Build every package in packaging/*/, sign the new ones, add them to the
# signed repo database and publish it all to the S3 bucket that serves the
# pacman repo. Run by .github/workflows/packages.yml as an unprivileged user
# that may `sudo pacman` (makepkg installs build dependencies); see
# packaging/README.md.
#
# Idempotent: a package whose exact file is already in the bucket is not
# rebuilt (PKGS_REBUILD=1 forces it), and a run with nothing new uploads
# nothing.
#
# Environment (all required unless a default is shown; never printed):
#   PKGS_S3_ENDPOINT           S3 endpoint URL
#   PKGS_S3_BUCKET             bucket holding <repo>/<arch>/...
#   PKGS_S3_ACCESS_KEY_ID      write key for that bucket
#   PKGS_S3_SECRET_ACCESS_KEY
#   PKGS_GPG_PRIVATE_KEY       armored secret key; must be the key in
#                              packaging/keys/bromigos.asc
#   PKGS_GPG_PASSPHRASE        its passphrase
#   PKGS_REPO=bromigos  PKGS_ARCH=x86_64  PKGS_KEEP=3 (versions kept per package)
#   PKGS_REBUILD=0      PKGS_ONLY= (space-separated package dirs, default all)
#   PKGS_GCS_BUCKET     optional: the public mirror, a Google Cloud Storage bucket that
#   PKGS_GCS_ACCESS_KEY_ID      gets a copy of the channel after every publish, under the
#   PKGS_GCS_SECRET_ACCESS_KEY  same lease (an HMAC key: GCS speaks S3). Unset, no mirror.
#                       PKGS_GCS_ENDPOINT=https://storage.googleapis.com
#   PKGS_MIRROR_ONLY=0  1: build nothing, only bring the mirror up to date with this channel
#   PKGS_CHANNEL=edge   the channel published: edge (every push to main) lives at
#                       <repo>/<arch>/ (the first layout, so pacman.conf's Server line
#                       never changed); stable (vX.Y.Z tags) and rc (vX.Y.Z-rcN tags)
#                       at <repo>/<channel>/<arch>/. Each has its own database and lease.
#   PKGS_REUSE          the channels a tag's publish takes a package from before building it
#                       (default: rc for stable, then edge; edge for rc; nothing for edge).
#                       A package's file name is its pkgver(), which names the commit it was
#                       built from, so the same name is the same build: copied with its
#                       signature (checked), never rebuilt. That's how an rc promoted to
#                       stable publishes the very files the rc channel tested.
export PACKAGER="bromigOS CI <packages@bromigos.org>"   # shown as Packager in pacman -Qi
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root=$(cd "$here/../.." && pwd)
repo=${PKGS_REPO:-bromigos}
arch=${PKGS_ARCH:-x86_64}
keep=${PKGS_KEEP:-3}
rebuild=${PKGS_REBUILD:-0}
channel=${PKGS_CHANNEL:-edge}
case "$channel" in
  edge) prefix="$repo/$arch" ;;
  stable|rc) prefix="$repo/$channel/$arch" ;;
  *) echo "publish: PKGS_CHANNEL must be edge, stable or rc (dev is a local repo: packaging/dev-repo.sh)" >&2; exit 2 ;;
esac
case "$channel" in
  stable) reuse=${PKGS_REUSE-rc edge} ;;
  rc) reuse=${PKGS_REUSE-edge} ;;
  *) reuse=${PKGS_REUSE-} ;;
esac

for v in PKGS_S3_ENDPOINT PKGS_S3_BUCKET PKGS_S3_ACCESS_KEY_ID \
         PKGS_S3_SECRET_ACCESS_KEY PKGS_GPG_PRIVATE_KEY PKGS_GPG_PASSPHRASE; do
  [[ -n "${!v:-}" ]] || { echo "publish: $v is not set" >&2; exit 2; }
done
[[ "$keep" =~ ^[1-9][0-9]*$ ]] || { echo "publish: PKGS_KEEP must be >= 1" >&2; exit 2; }

work=$(mktemp -d)
export GNUPGHOME="$work/gnupg"
cleanup() {
  declare -F release >/dev/null && release
  gpgconf --kill all >/dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT
mkdir -m 700 "$GNUPGHOME" "$work/repo" "$work/out"

# ── Signing key ──────────────────────────────────────────────────────────────
# An ephemeral keyring. The passphrase is preset in gpg-agent, so makepkg-
# style tools (repo-add --sign) sign without a prompt; neither the key nor
# the passphrase is ever an argument or a file outside $work.
echo "allow-preset-passphrase" > "$GNUPGHOME/gpg-agent.conf"
gpg --batch --quiet --import <<<"$PKGS_GPG_PRIVATE_KEY" 2>/dev/null
unset PKGS_GPG_PRIVATE_KEY
fpr=$(gpg --batch --with-colons --list-secret-keys | awk -F: '/^fpr:/ { print $10; exit }')
want=$(gpg --batch --with-colons --import-options show-only --import \
  "$root/packaging/keys/bromigos.asc" 2>/dev/null | awk -F: '/^fpr:/ { print $10; exit }')
if [[ -z "$fpr" || "$fpr" != "$want" ]]; then
  echo "publish: the signing key is not the one in packaging/keys/bromigos.asc" >&2
  exit 1
fi
preset=/usr/lib/gnupg/gpg-preset-passphrase
gpg-connect-agent /bye >/dev/null 2>&1
gpg --batch --with-colons --with-keygrip --list-secret-keys "$fpr" \
  | awk -F: '/^grp:/ { print $10 }' | while read -r grip; do
      "$preset" --preset "$grip" <<<"$PKGS_GPG_PASSPHRASE"
    done
unset PKGS_GPG_PASSPHRASE
echo "$fpr:6:" | gpg --batch --quiet --import-ownertrust
export GPGKEY="$fpr"
echo "publish: signing as $fpr"

# ── The bucket (rclone, configured from the environment only) ────────────────
export RCLONE_CONFIG_PKGS_TYPE=s3
export RCLONE_CONFIG_PKGS_PROVIDER=Other
export RCLONE_CONFIG_PKGS_ENDPOINT="$PKGS_S3_ENDPOINT"
export RCLONE_CONFIG_PKGS_ACCESS_KEY_ID="$PKGS_S3_ACCESS_KEY_ID"
export RCLONE_CONFIG_PKGS_SECRET_ACCESS_KEY="$PKGS_S3_SECRET_ACCESS_KEY"
export RCLONE_CONFIG_PKGS_REGION=us-east-1
export RCLONE_CONFIG_PKGS_FORCE_PATH_STYLE=true
export RCLONE_CONFIG_PKGS_NO_CHECK_BUCKET=true
unset PKGS_S3_ACCESS_KEY_ID PKGS_S3_SECRET_ACCESS_KEY
dest="pkgs:$PKGS_S3_BUCKET/$prefix"
echo "publish: channel $channel -> $prefix"
rcl() { rclone --config /dev/null --stats 0 "$@"; }

# ── The public mirror (Google Cloud Storage), when PKGS_GCS_BUCKET is set ────
# The homelab bucket stays the primary: every read below is from it. The mirror gets a
# copy of the channel once the primary is published (mirror_channel, below).
mirror=0
if [[ -n "${PKGS_GCS_BUCKET:-}" ]]; then
  for v in PKGS_GCS_ACCESS_KEY_ID PKGS_GCS_SECRET_ACCESS_KEY; do
    [[ -n "${!v:-}" ]] || { echo "publish: PKGS_GCS_BUCKET is set but $v isn't" >&2; exit 2; }
  done
  export RCLONE_CONFIG_GCS_TYPE=s3
  export RCLONE_CONFIG_GCS_PROVIDER=GCS
  export RCLONE_CONFIG_GCS_ENDPOINT="${PKGS_GCS_ENDPOINT:-https://storage.googleapis.com}"
  export RCLONE_CONFIG_GCS_ACCESS_KEY_ID="$PKGS_GCS_ACCESS_KEY_ID"
  export RCLONE_CONFIG_GCS_SECRET_ACCESS_KEY="$PKGS_GCS_SECRET_ACCESS_KEY"
  export RCLONE_CONFIG_GCS_NO_CHECK_BUCKET=true
  unset PKGS_GCS_ACCESS_KEY_ID PKGS_GCS_SECRET_ACCESS_KEY
  gdest="gcs:$PKGS_GCS_BUCKET/$prefix"
  mirror=1
  echo "publish: mirroring to the public bucket too"
elif [[ "${PKGS_MIRROR_ONLY:-0}" == 1 ]]; then
  echo "publish: PKGS_MIRROR_ONLY=1 needs PKGS_GCS_BUCKET" >&2; exit 2
fi

rcl lsf --files-only "$dest" > "$work/listing" 2>/dev/null || : > "$work/listing"
in_bucket() { grep -qxF "$1" "$work/listing"; }

# The channels a package may be reused from, and what each holds now.
declare -A reuse_dir=()
for ch in $reuse; do
  case "$ch" in
    edge) reuse_dir[$ch]="pkgs:$PKGS_S3_BUCKET/$repo/$arch" ;;
    stable|rc) reuse_dir[$ch]="pkgs:$PKGS_S3_BUCKET/$repo/$ch/$arch" ;;
    *) echo "publish: PKGS_REUSE: no channel $ch" >&2; exit 2 ;;
  esac
  [[ $ch == "$channel" ]] && continue
  rcl lsf --files-only "${reuse_dir[$ch]}" > "$work/listing.$ch" 2>/dev/null || : > "$work/listing.$ch"
done
# reuse_from NAME FILE...: copy every file (and its .sig) from the first channel that has
# them all into $PKGDEST, signatures checked; false when none does, or a copy fails.
reuse_from() {
  local name=$1 ch f ok
  shift
  for ch in $reuse; do
    [[ $ch == "$channel" || ! -f "$work/listing.$ch" ]] && continue
    ok=1
    for f in "$@"; do
      grep -qxF "$(basename "$f")" "$work/listing.$ch" && grep -qxF "$(basename "$f").sig" "$work/listing.$ch" || ok=0
    done
    (( ok )) || continue
    for f in "$@"; do
      rcl copyto "${reuse_dir[$ch]}/$(basename "$f")" "$f" && rcl copyto "${reuse_dir[$ch]}/$(basename "$f").sig" "$f.sig" \
        && gpg --batch --quiet --verify "$f.sig" "$f" 2>/dev/null || { ok=0; break; }
    done
    if (( ok )); then
      echo "publish: $name: $(basename "$1") reused from $ch (the same build; not rebuilt)"
      return 0
    fi
    echo "publish: $name: couldn't copy it from $ch; building it"
    rm -f "$@" "${@/%/.sig}"
  done
  return 1
}

# ── The bootstrap: install.sh and the public key, at <repo>/ (docs/install.md) ─────────
# What `curl <server>/bromigos/install.sh | bash -s -- --repo <server>` fetches; the key's
# fingerprint is pinned in install.sh itself. Copied on every run (--checksum: only when
# changed), whatever is built, so a fix to the bootstrap alone goes out too.
for f in install.sh packaging/keys/bromigos.asc; do
  if [[ -f "$root/$f" ]]; then rcl copyto --checksum "$root/$f" "pkgs:$PKGS_S3_BUCKET/$repo/$(basename "$f")"; fi
  if [[ -f "$root/$f" ]] && (( mirror )); then
    rcl copyto --checksum --header-upload "Cache-Control: no-cache" "$root/$f" "gcs:$PKGS_GCS_BUCKET/$repo/$(basename "$f")"
  fi
done

db="$work/repo/$repo.db.tar.gz"

# ── One publisher at a time, across repositories ─────────────────────────────
# A workflow's concurrency group keeps one repository's runs apart, but bromigOS and
# vector (bromigos-vector) both rewrite this one database: a lease object in the bucket
# serialises the read-modify-write (database, upload, prune). A lease older than 20
# minutes is a dead run's and is taken over.
lock="$dest/.publish-lock"
me="${GITHUB_REPOSITORY:-local}#${GITHUB_RUN_ID:-$$}.$RANDOM"
held_by_me=0
acquire() {
  local deadline=$(( $(date +%s) + 1800 )) now held t
  while :; do
    now=$(date +%s)
    held=$(rcl cat "$lock" 2>/dev/null || true)
    t=${held##* }
    if [[ -z "$held" || ! "$t" =~ ^[0-9]+$ ]] || (( now - t > 1200 )); then
      printf '%s %s\n' "$me" "$now" | rcl rcat "$lock"
      sleep 3
      if [[ "$(rcl cat "$lock" 2>/dev/null || true)" == "$me $now" ]]; then held_by_me=1; return 0; fi
      continue
    fi
    (( now < deadline )) || { echo "publish: ${held%% *} still holds the repo lock; giving up" >&2; exit 1; }
    echo "publish: waiting for ${held%% *} to finish publishing"
    sleep 20
  done
}
release() {
  (( held_by_me )) || return 0
  [[ "$(rcl cat "$lock" 2>/dev/null || true)" == "$me "* ]] && rcl deletefile "$lock" 2>/dev/null
  held_by_me=0
}

# ── The mirror's copy of the channel ─────────────────────────────────────────
# Run under the lease, so no other publish changes the primary meanwhile. The order keeps
# the mirror consistent for a pacman reading it at any moment:
#   1. new packages and their signatures (and the signed lab catalog);
#   2. the databases, each signature straight after its database;
#   3. only then, whatever the primary pruned.
# The old database names only files that are still there until step 3. Databases and the
# catalog say Cache-Control: no-cache, so a public cache never serves a stale database
# beside a fresh signature. --checksum compares MD5s, which both buckets keep.
mirror_channel() {
  local f base nocache=(--header-upload "Cache-Control: no-cache")
  rcl copy --checksum --include '/*.pkg.tar.*' "$dest" "$gdest"
  rcl copy --checksum "${nocache[@]}" --include '/lab/**' "$dest" "$gdest"
  rcl lsf --files-only "$dest" > "$work/listing.mirror"
  for base in "$repo.files" "$repo.db"; do
    for f in "$base.tar.gz" "$base.tar.gz.sig" "$base" "$base.sig"; do
      grep -qxF "$f" "$work/listing.mirror" || continue
      rcl copyto --checksum "${nocache[@]}" "$dest/$f" "$gdest/$f"
    done
  done
  # Nothing is left to copy, so this only deletes what the primary no longer has.
  rcl sync --checksum --exclude '/.publish-lock' "$dest" "$gdest"
  echo "publish: the public mirror matches $prefix"
}
# mirror_if_behind: compare first, so a run that changed nothing doesn't take the lease.
mirror_if_behind() {
  (( mirror )) || return 0
  if rcl check --checksum --exclude '/.publish-lock' "$dest" "$gdest" >/dev/null 2>&1; then
    echo "publish: the public mirror is up to date"
    return 0
  fi
  acquire
  mirror_channel
}

if [[ "${PKGS_MIRROR_ONLY:-0}" == 1 ]]; then
  mirror_if_behind
  exit 0
fi

# ── Build ────────────────────────────────────────────────────────────────────
if [[ -n "${PKGS_ONLY:-}" ]]; then
  read -r -a dirs <<<"$PKGS_ONLY"
else
  dirs=()
  for d in "$root"/packaging/*/; do
    [[ -f "$d/PKGBUILD" ]] && dirs+=("$(basename "$d")")
  done
fi

export PKGDEST="$work/out"
built=()
for name in "${dirs[@]}"; do
  dir="$root/packaging/$name"
  echo "::group::$name"
  pushd "$dir" >/dev/null
  # Build-time dependencies only (makedepends, checkdepends): a package's runtime
  # depends may be our own packages (bromigos-live needs bromigos-core), which the
  # build container has no repo for, and building never needs them. Hence --nodeps.
  mapfile -t need < <(makepkg --printsrcinfo | awk -F' = ' '/^\t(makedepends|checkdepends) = / { print $2 }' | sort -u)
  if (( ${#need[@]} )); then sudo pacman -S --needed --noconfirm "${need[@]}"; fi
  # Fetch, prepare and run pkgver() (which rewrites pkgver= in the PKGBUILD),
  # so --packagelist below names the files this commit would produce.
  makepkg --nobuild --nodeps --noconfirm
  mapfile -t files < <(makepkg --packagelist)
  missing=0
  for f in "${files[@]}"; do in_bucket "$(basename "$f")" || missing=1; done
  if (( missing == 0 && rebuild != 1 )); then
    echo "publish: $name: $(basename "${files[0]}") is already published"
  elif (( rebuild != 1 )) && [[ -n "$reuse" ]] && reuse_from "$name" "${files[@]}"; then
    for f in "${files[@]}"; do built+=("$f"); done
  else
    makepkg --nodeps --noconfirm --noextract --force
    for f in "${files[@]}"; do
      # --packagelist can name a -debug package makepkg then doesn't make.
      [[ -f "$f" ]] || { echo "publish: $name: no $(basename "$f"), skipped"; continue; }
      gpg --batch --quiet --detach-sign --no-armor --use-agent -u "$fpr" "$f"
      built+=("$f")
    done
  fi
  popd >/dev/null
  echo "::endgroup::"
done

if (( ${#built[@]} == 0 )); then
  echo "publish: nothing new to publish"
  mirror_if_behind   # catches up after a run whose mirror step failed
  exit 0
fi

# ── Database ─────────────────────────────────────────────────────────────────
# Fetched now, under the lock, so another repository's publish in the meantime is kept.
acquire
rcl lsf --files-only "$dest" > "$work/listing" 2>/dev/null || : > "$work/listing"
for f in "$repo.db.tar.gz" "$repo.db.tar.gz.sig" "$repo.files.tar.gz" "$repo.files.tar.gz.sig"; do
  if in_bucket "$f"; then rcl copyto "$dest/$f" "$work/repo/$f"; fi   # a failed copy stops the run
done
# --verify checks the current database's signature before touching it;
# --sign signs the new one. repo-add replaces an older entry of the same name.
repo-add --verify --sign --key "$fpr" "$db" "${built[@]}"

# ── Upload: packages first, then the database, so the database never names a
# file the bucket doesn't have. No symlinks in S3: the .db/.files names are
# copies of the .tar.gz files pacman never reads directly.
for f in "${built[@]}"; do
  rcl copyto "$f" "$dest/$(basename "$f")"
  rcl copyto "$f.sig" "$dest/$(basename "$f").sig"
done
for base in "$repo.db" "$repo.files"; do
  rcl copyto "$work/repo/$base.tar.gz" "$dest/$base.tar.gz"
  rcl copyto "$work/repo/$base.tar.gz.sig" "$dest/$base.tar.gz.sig"
  rcl copyto "$work/repo/$base.tar.gz" "$dest/$base"
  rcl copyto "$work/repo/$base.tar.gz.sig" "$dest/$base.sig"
done
printf 'publish: published %s\n' "${built[@]##*/}"

# ── The lab model catalog, signed, beside the packages (docs/lab-models.md) ──────
# `bromigos lab models refresh` fetches <server>/lab/models.toml and its detached signature
# (checked with the keyring bromigos-keyring installs), so a catalog update reaches every
# channel's users on demand, whatever their package versions. Only when its package was built.
if printf '%s\n' "${built[@]##*/}" | grep -q '^bromigos-lab-catalog-'; then
  cp "$root/homelab/share/lab/models.toml" "$work/models.toml"
  gpg --batch --quiet --detach-sign --no-armor --use-agent -u "$fpr" "$work/models.toml"
  rcl copyto "$work/models.toml" "$dest/lab/models.toml"
  rcl copyto "$work/models.toml.sig" "$dest/lab/models.toml.sig"
  echo "publish: the lab model catalog, signed, at lab/models.toml"
fi

# ── Prune: keep the newest $keep versions of each package ───────────────────
# <name>-<pkgver>-<pkgrel>-<arch>.pkg.tar.<ext>: the name is all but the last
# three dash-separated fields. Lines: name<TAB>pkgver-pkgrel<TAB>file.
rcl lsf --files-only --include '*.pkg.tar.*' --exclude '*.sig' "$dest" \
  | sed -nE 's/^((.+)-([^-]+-[^-]+)-[^-]+\.pkg\.tar\.[a-z0-9]+)$/\2\t\3\t\1/p' > "$work/pkgs"
current=$(tar -xzOf "$db" --wildcards '*/desc' | awk '/^%FILENAME%$/ { getline; print }')
cut -f1 "$work/pkgs" | sort -u | while read -r name; do
  # This package's versions, oldest first by vercmp (pacman's own order).
  mapfile -t l < <(awk -F'\t' -v n="$name" '$1 == n { print $2 "\t" $3 }' "$work/pkgs")
  for ((i = 1; i < ${#l[@]}; i++)); do
    for ((j = i; j > 0; j--)); do
      (( $(vercmp "${l[j-1]%%$'\t'*}" "${l[j]%%$'\t'*}") > 0 )) || break
      t=${l[j]}; l[j]=${l[j-1]}; l[j-1]=$t
    done
  done
  for ((i = 0; i < ${#l[@]} - keep; i++)); do
    old=${l[i]#*$'\t'}
    grep -qxF "$old" <<<"$current" && continue   # never the file the db names
    rcl deletefile "$dest/$old"
    rcl deletefile "$dest/$old.sig" 2>/dev/null || true
    echo "publish: pruned $old"
  done
done

# ── The public mirror, last: the primary is published whatever happens here ──
# A failure fails the run, so it shows; the next run catches the mirror up (mirror_if_behind).
# Called plainly, never in an || list, where bash would ignore set -e inside it and carry on
# to the databases after a failed package copy.
if (( mirror )); then
  mirror_channel
fi
