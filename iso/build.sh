#!/usr/bin/env bash
# Build the bromigOS ISO (docs/iso.md). mkarchiso needs root and a chroot, so this runs
# in a privileged archlinux container (Docker) on any machine; nothing is installed on
# the host. The medium carries an offline copy of the repositories (Arch's core and extra
# for everything it needs, and bromigOS's), so an install needs no network.
#
#   iso/build.sh --repo URL [--ca FILE] [--out DIR] [--test-key FILE] [--keep-work]
#
#   --repo URL      bromigOS's package repository (https://…; it must be reachable from
#                   here; the medium remembers it as the installed system's repository)
#   --channel NAME  stable (default: tagged releases), rc, or edge (every push to main):
#                   the packages on the medium, and the installed system's channel
#   --ca FILE       that repository's TLS CA, when it has its own (it goes on the medium
#                   too, for the installed system)
#   --hosts "IP NAME"  the repository host's address, when DNS doesn't give it
#   --out DIR       where the ISO lands (default: a scratch dir, printed)
#   --test-key FILE a test build: this SSH public key signs in as the live user, sshd is
#                   on, and the kernel console is on the serial port too (iso/test.sh)
#   --keep-work     keep mkarchiso's work dir after the build (the image's root, to look
#                   into); every build starts it afresh
#
# Idempotent: the package downloads are cached in --out/cache; a rebuild redoes only
# the image. The result: <out>/bromigos-<version>-x86_64.iso and its .sha256.
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root=$(cd "$here/.." && pwd)

repo='' ca='' hosts='' out='' testkey='' keep=0 channel=stable
while (($#)); do
    case $1 in
        --repo) repo=$2; shift 2 ;; --ca) ca=$2; shift 2 ;; --hosts) hosts=$2; shift 2 ;; --channel) channel=$2; shift 2 ;;
        --out) out=$2; shift 2 ;; --test-key) testkey=$2; shift 2 ;; --keep-work) keep=1; shift ;;
        -h|--help) sed -n '2,23p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "iso/build.sh: unknown option $1" >&2; exit 2 ;;
    esac
done
[[ -n $repo ]] || { echo "iso/build.sh: --repo URL is required (the package repository)" >&2; exit 2; }
command -v docker >/dev/null || { echo "iso/build.sh: docker is needed (a privileged archlinux container builds the image)" >&2; exit 2; }
[[ -n $out ]] || out=${BROMIGOS_ISO_OUT:-${XDG_CACHE_HOME:-$HOME/.cache}/bromigos-iso}
mkdir -p "$out/cache" "$out/work"
out=$(cd "$out" && pwd)

mounts=(-v "$root:/src:ro" -v "$out:/out")
case $channel in stable|rc|edge) ;; *) echo "iso/build.sh: --channel is stable, rc or edge" >&2; exit 2 ;; esac
env=(-e "ISO_REPO=$repo" -e "ISO_CHANNEL=$channel" -e "ISO_KEEP_WORK=$keep")
if [[ -n $ca ]]; then mounts+=(-v "$(realpath "$ca"):/in/repo-ca.crt:ro"); fi
if [[ -n $testkey ]]; then mounts+=(-v "$(realpath "$testkey"):/in/test_key.pub:ro"); fi
addhost=(); [[ -n $hosts ]] && addhost=(--add-host "${hosts#* }:${hosts%% *}")

# --privileged: pacstrap and arch-chroot mount proc/sys/dev in the work dir; mksquashfs
# and xorriso need nothing special. The work dir is a volume (tmpfs would eat RAM).
docker run --rm --privileged "${addhost[@]}" "${mounts[@]}" "${env[@]}" \
    -w /src/iso archlinux:latest /src/iso/build-in-container.sh
ls -la "$out"/bromigos-*.iso 2>/dev/null | tail -1
