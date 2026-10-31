#!/usr/bin/env bash
# The packages a medium needs that this ref has and the channel doesn't (docs/iso.md, "What CI
# does with it"): CI's ISO builds use them as a local repository (iso/build.sh --local-repo),
# ahead of the published channel, so a package that's new in a pull request, or changed in it,
# never breaks the ISO's build.
#
#   iso/ci-local-packages.sh SRC OUT [--channel edge|rc|stable] [--base REF] [--list]
#
# A package under SRC/packaging/ is built when one of its names isn't in the channel's public
# database, or, with --base, when this ref changed a file under one of its paths (the
# PKGBUILD's _paths; else its own folder) since REF. Each is built the way
# packaging/ci/publish.sh builds it: in a clean archlinux:base-devel container, its
# makedepends and checkdepends installed from Arch's repositories, then makepkg --nodeps
# (here --nocheck too: packages.yml runs the checks). OUT gets the package files, nothing when
# nothing is needed. Prints what it built and why (--list: only what it would build). What the
# public mirror never carries (publish.sh's public_skip: 1password) is never built.
#
# Environment: PKGS_PUBLIC_URL (default https://pkgs.bromigos.org), the public mirror read for
# the channel's database.
set -euo pipefail
src=$(realpath "${1:?SRC}"); out=${2:?OUT}; shift 2
channel=edge base='' list=0
while (($#)); do
    case $1 in
        --channel) channel=$2; shift 2 ;; --base) base=$2; shift 2 ;; --list) list=1; shift ;;
        *) echo "iso/ci-local-packages.sh: unknown option $1" >&2; exit 2 ;;
    esac
done
mkdir -p "$out"; out=$(realpath "$out")
public=${PKGS_PUBLIC_URL:-https://pkgs.bromigos.org}

# what the channel has: the names in its public database
if [[ $channel == edge ]]; then path=bromigos/x86_64; else path=bromigos/$channel/x86_64; fi
names=$(mktemp)
if curl -fsSL --retry 3 "$public/$path/bromigos.db" -o "$names.db"; then
    bsdtar -tf "$names.db" | sed -n 's|^\(.*\)-[^-]*-[^-]*/$|\1|p' | sort -u > "$names"
else
    echo "the channel's database couldn't be read: building every package this ref has" >&2
    : > "$names"
fi
changed=''
if [[ -n $base ]]; then
    changed=$(git -C "$src" diff --name-only "$base"...HEAD 2>/dev/null || git -C "$src" diff --name-only "$base" HEAD)
fi

read -r -a skip < <(sed -n 's/^public_skip=(\(.*\))/\1/p' "$src/packaging/ci/publish.sh")
want=()
for pb in "$src"/packaging/*/PKGBUILD; do
    dir=$(dirname "$pb"); name=$(basename "$dir")
    [[ " ${skip[*]:-} " == *" $name "* ]] && continue
    # each package's names and paths, from its PKGBUILD (sourced in a subshell, as makepkg does)
    read -r -a info < <(cd "$dir" && startdir=$dir bash -c 'source ./PKGBUILD >/dev/null 2>&1
        printf "%s " "${pkgname[@]}"; printf "| "; printf "%s " "${_paths[@]:-}"; echo')
    pkgnames=() paths=() side=names
    for w in "${info[@]}"; do
        if [[ $w == '|' ]]; then side=paths; continue; fi
        if [[ $side == names ]]; then pkgnames+=("$w"); else paths+=("$w"); fi
    done
    (( ${#paths[@]} )) || paths=("packaging/$name")
    why=''
    for n in "${pkgnames[@]}"; do
        grep -qxF "$n" "$names" || { why="not in $channel yet"; break; }
    done
    if [[ -z $why && -n $changed ]]; then
        for p in "${paths[@]}" "packaging/$name"; do
            if grep -q "^${p%/}\(/\|$\)" <<<"$changed"; then why="changed here"; break; fi
        done
    fi
    [[ -n $why ]] && { want+=("$name"); echo "$name: $why"; }
done
rm -f "$names" "$names.db"
(( ${#want[@]} )) || { echo "every package is in $channel as this ref has it"; exit 0; }
(( list )) && exit 0

docker run --rm -i -v "$src:/src:ro" -v "$out:/out" -e "PKGS=${want[*]}" archlinux:base-devel bash -s <<'BUILD'
set -euo pipefail
pacman -Syu --noconfirm --needed git sudo >/dev/null
useradd -m builder
echo "builder ALL=(root) NOPASSWD: /usr/bin/pacman" > /etc/sudoers.d/builder
git config --system --add safe.directory '*'
cp -a /src /home/builder/src && chown -R builder: /home/builder/src
chown builder /out
for p in $PKGS; do
    echo "::group::$p"
    if sudo -u builder env P="$p" bash -s <<'ONE'
set -euo pipefail
cd "/home/builder/src/packaging/$P"
mapfile -t need < <(makepkg --printsrcinfo | sed -n 's/^\t\(makedepends\|checkdepends\) = //p' | sort -u)
if (( ${#need[@]} )); then sudo pacman -S --needed --noconfirm "${need[@]}" >/dev/null; fi
PKGDEST=/out makepkg --nodeps --nocheck --noconfirm --skippgpcheck
ONE
    then echo "::endgroup::"; echo "built $p"
    else echo "::endgroup::"; echo "::warning::$p didn't build here: the medium takes the channel's, if it has one"
    fi
done
rm -f /out/*-debug-*.pkg.tar.zst
ls /out
BUILD
