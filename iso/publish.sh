#!/usr/bin/env bash
# Signs a built ISO and publishes it to the public bucket behind https://pkgs.bromigos.org
# (docs/iso.md, "Where the ISO lives"). The ISO workflow (.github/workflows/iso.yml) runs it;
# it runs the same by hand with the same environment.
#
#   iso/publish.sh sign ISO
#       ISO.sig: a detached, armoured signature by the package signing key, in a throwaway
#       GnuPG home, then verified against packaging/keys/bromigos.asc alone
#   iso/publish.sh upload ISO --channel stable|edge [--tag TAG]
#       the ISO, its .sha256 and .sig, and ISO.json (what the Download page and the release
#       notes read) into the version's folder; then downloads it back, as a stranger, and
#       checks the checksum
#   iso/publish.sh pointers --channel stable|edge [--keep N] [--out DIR]
#       the newest version's index.json (every ISO of that version) and the channel's
#       latest.json, then removes all but the newest N versions (stable: 3, edge: 1)
#
# The bucket's layout (the version is the release's, without the v; edge's is the build's date):
#
#   iso/latest.json                                   the newest stable version's index
#   iso/<version>/bromigos-<version>-x86_64.iso       + .sha256, .sig, .json
#   iso/<version>/bromigos-fieldkit-<version>-x86_64.iso   the Field Kit, when it's built
#   iso/<version>/index.json
#   iso/edge/latest.json, iso/edge/<version>/…        the weekly edge build, the newest only
#
# Environment (never printed, never on a command line): PKGS_PUBLIC_ENDPOINT,
# PKGS_PUBLIC_BUCKET, PKGS_PUBLIC_ACCESS_KEY_ID, PKGS_PUBLIC_SECRET_ACCESS_KEY (the R2 bucket,
# as packaging/ci/publish.sh uses it); PKGS_GPG_PRIVATE_KEY, PKGS_GPG_PASSPHRASE (sign);
# ISO_PUBLIC_URL (default: install.sh's PUBLIC_REPO).
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root=$(cd "$here/.." && pwd)
FPR=393E7D54F7DE58FE75B97214947C9D6193D3DD8B

die() { echo "iso/publish.sh: $*" >&2; exit 1; }
cmd=${1:-}; shift || true
iso='' channel='' tag='' keep='' out=''
while (($#)); do
    case $1 in
        --channel) channel=$2; shift 2 ;; --tag) tag=$2; shift 2 ;; --keep) keep=$2; shift 2 ;; --out) out=$2; shift 2 ;;
        -h|--help) sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*) die "unknown option $1" ;;
        *) iso=$1; shift ;;
    esac
done
public=${ISO_PUBLIC_URL:-$(sed -n "s/^PUBLIC_REPO=\([^ ]*\).*/\1/p" "$root/install.sh" | tr -d "'\"")}
[[ -n $public ]] || die "no public address: set ISO_PUBLIC_URL"
public=${public%/}

rcl() { rclone --config /dev/null --stats 0 "$@"; }
remote() {
    local v
    for v in PKGS_PUBLIC_ENDPOINT PKGS_PUBLIC_BUCKET PKGS_PUBLIC_ACCESS_KEY_ID PKGS_PUBLIC_SECRET_ACCESS_KEY; do
        [[ -n ${!v:-} ]] || die "$v isn't set"
    done
    command -v rclone >/dev/null || die "rclone is needed"
    export RCLONE_CONFIG_PUB_TYPE=s3 RCLONE_CONFIG_PUB_PROVIDER=Cloudflare RCLONE_CONFIG_PUB_REGION=auto \
        RCLONE_CONFIG_PUB_NO_CHECK_BUCKET=true RCLONE_CONFIG_PUB_ENDPOINT=$PKGS_PUBLIC_ENDPOINT \
        RCLONE_CONFIG_PUB_ACCESS_KEY_ID=$PKGS_PUBLIC_ACCESS_KEY_ID RCLONE_CONFIG_PUB_SECRET_ACCESS_KEY=$PKGS_PUBLIC_SECRET_ACCESS_KEY
    unset PKGS_PUBLIC_ACCESS_KEY_ID PKGS_PUBLIC_SECRET_ACCESS_KEY
    B="pub:$PKGS_PUBLIC_BUCKET"
}
channel_dir() {         # where a channel's versions live in the bucket
    case $channel in stable) echo iso ;; edge) echo iso/edge ;; *) die "--channel is stable or edge" ;; esac
}
# bromigos-0.1.3-x86_64.iso -> its edition (bromigos, bromigos-fieldkit) and version
parse_name() {
    local f=${1%-x86_64.iso}
    [[ $f =~ ^(bromigos(-[a-z]+)?)-([0-9][0-9A-Za-z._+-]*)$ ]] || die "not an ISO's name: $1"
    edition=${BASH_REMATCH[1]} version=${BASH_REMATCH[3]}
}

case $cmd in
    sign)
        [[ -f $iso ]] || die "sign ISO"
        [[ -n ${PKGS_GPG_PRIVATE_KEY:-} ]] || die "PKGS_GPG_PRIVATE_KEY isn't set"
        GNUPGHOME=$(mktemp -d); export GNUPGHOME; chmod 700 "$GNUPGHOME"
        trap 'gpgconf --kill all 2>/dev/null; rm -rf "$GNUPGHOME"' EXIT
        printf '%s\n' "$PKGS_GPG_PRIVATE_KEY" | gpg --batch --quiet --import 2>/dev/null
        printf '%s' "${PKGS_GPG_PASSPHRASE:-}" | gpg --batch --quiet --pinentry-mode loopback --passphrase-fd 0 \
            --local-user "$FPR" --armor --detach-sign --yes --output "$iso.sig" "$iso"
        gpgconf --kill all; rm -rf "$GNUPGHOME"
        # verified with the published key alone, as someone downloading it would
        GNUPGHOME=$(mktemp -d); chmod 700 "$GNUPGHOME"
        gpg --batch --quiet --import "$root/packaging/keys/bromigos.asc" 2>/dev/null
        gpg --batch --status-fd 1 --verify "$iso.sig" "$iso" 2>/dev/null | grep -q "^\[GNUPG:\] VALIDSIG $FPR " \
            || die "the signature doesn't verify against packaging/keys/bromigos.asc"
        echo "signed: $(basename "$iso").sig ($FPR)"
        ;;
    upload)
        [[ -f $iso && -f $iso.sig ]] || die "upload ISO: the ISO and its .sig (sign first)"
        [[ $channel == stable || $channel == edge ]] || die "--channel is stable or edge"
        name=$(basename "$iso"); parse_name "$name"
        dir=$(dirname "$iso")
        [[ -f $iso.sha256 ]] || (cd "$dir" && sha256sum "$name" > "$name.sha256")
        sum=$(awk '{print $1; exit}' "$iso.sha256")
        [[ $(sha256sum "$iso" | awk '{print $1}') == "$sum" ]] || die "$name doesn't match its .sha256"
        remote
        path="$(channel_dir)/$version"
        url="$public/$path/$name"
        # Secure Boot: the medium carries shim and the certificate to enroll (docs/secureboot.md)
        sb=false
        xorriso -indev "$iso" -find / -name ENROLL_THIS_KEY_IN_MOKMANAGER.cer 2>/dev/null | grep -q MOKMANAGER && sb=true
        python3 - "$iso" "$edition" "$version" "$channel" "$sum" "$url" "${tag:-}" "${GITHUB_SHA:-}" "$sb" > "$iso.json" <<'PY'
import json, os, sys, time
iso, edition, version, channel, sha, url, tag, commit, sb = sys.argv[1:10]
json.dump({
    "edition": edition, "file": os.path.basename(iso), "version": version, "channel": channel,
    "tag": tag or None, "commit": commit or None,
    "size": os.path.getsize(iso), "sha256": sha,
    "url": url, "sha256_url": url + ".sha256", "sig_url": url + ".sig", "secure_boot": sb == "true",
    "built": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(os.path.getmtime(iso))),
    "published": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
}, sys.stdout, indent=2)
print()
PY
        echo "==> $name to $path/ ($(du -h "$iso" | cut -f1))"
        # one object, in parts of 64 MiB (R2 takes up to 10,000 parts); the version's files
        # never change once published, so they may be cached for good
        rcl copyto --s3-chunk-size 64M --s3-upload-concurrency 8 \
            --header-upload "Content-Type: application/x-iso9660-image" \
            --header-upload "Cache-Control: public, max-age=31536000, immutable" \
            "$iso" "$B/$path/$name"
        rcl copyto --header-upload "Content-Type: text/plain; charset=utf-8" "$iso.sha256" "$B/$path/$name.sha256"
        rcl copyto --header-upload "Content-Type: application/pgp-signature" "$iso.sig" "$B/$path/$name.sig"
        rcl copyto --header-upload "Content-Type: application/json" --header-upload "Cache-Control: no-cache" "$iso.json" "$B/$path/$name.json"
        # as a stranger: the public address, no credentials, the whole file
        echo "==> checking $url"
        got=$(curl -fsSL --retry 3 "$url" | sha256sum | awk '{print $1}')
        [[ $got == "$sum" ]] || die "the published $name has the checksum $got, not $sum"
        curl -fsSL --retry 3 "$url.sha256" | grep -q "^$sum " || die "the published .sha256 isn't the ISO's"
        echo "published: $url"
        echo "url=$url" >> "${GITHUB_OUTPUT:-/dev/null}"
        ;;
    pointers)
        [[ $channel == stable || $channel == edge ]] || die "--channel is stable or edge"
        [[ -n $keep ]] || { [[ $channel == stable ]] && keep=3 || keep=1; }
        [[ $keep =~ ^[1-9][0-9]*$ ]] || die "--keep is a number, 1 or more"
        out=${out:-$(mktemp -d)}; mkdir -p "$out"
        remote
        cdir=$(channel_dir)
        # the channel's versions: stable's are X.Y.Z (the edge folder isn't one), newest last
        mapfile -t versions < <(rcl lsf --dirs-only "$B/$cdir/" | sed 's|/$||' \
            | { if [[ $channel == stable ]]; then grep -E '^[0-9]+\.[0-9]+\.[0-9]+$'; else grep -E '^[0-9]'; fi; } | sort -V || true)
        ((${#versions[@]})) || die "no $channel versions in $cdir/"
        newest=${versions[-1]}
        for v in "${versions[@]}"; do
            mkdir -p "$out/$v"
            rcl copy --include '*.iso.json' "$B/$cdir/$v/" "$out/$v/"
            # every ISO of the version (newest edition order: the desktop first), as one index
            python3 - "$out/$v" "$v" "$channel" > "$out/$v/index.json" <<'PY'
import glob, json, os, sys, time
d, version, channel = sys.argv[1:4]
isos = [json.load(open(f)) for f in sorted(glob.glob(os.path.join(d, "*.iso.json")))]
isos.sort(key=lambda m: (m["edition"] != "bromigos", m["edition"]))
tags = [m["tag"] for m in isos if m.get("tag")]
json.dump({"channel": channel, "version": version, "tag": tags[0] if tags else None,
           "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "isos": isos},
          sys.stdout, indent=2)
print()
PY
            if [[ $(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["isos"]))' "$out/$v/index.json") -gt 0 ]]; then
                rcl copyto --header-upload "Content-Type: application/json" --header-upload "Cache-Control: no-cache" \
                    "$out/$v/index.json" "$B/$cdir/$v/index.json"
            fi
        done
        cp "$out/$newest/index.json" "$out/latest.json"
        rcl copyto --header-upload "Content-Type: application/json" --header-upload "Cache-Control: no-cache" \
            "$out/latest.json" "$B/$cdir/latest.json"
        echo "latest $channel: $newest ($public/$cdir/latest.json)"
        # what's kept: the newest $keep versions; older ones are removed from the bucket
        n=${#versions[@]}
        if (( n > keep )); then
            for v in "${versions[@]:0:n-keep}"; do
                echo "removing $cdir/$v/ (keeping the newest $keep)"
                rcl purge "$B/$cdir/$v"
            done
        fi
        echo "version=$newest" >> "${GITHUB_OUTPUT:-/dev/null}"
        echo "index=$out/$newest/index.json" >> "${GITHUB_OUTPUT:-/dev/null}"
        ;;
    *) sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
