#!/usr/bin/env bash
# Build bromigOS's packages into a local pacman repository, for the `dev` channel:
#
#   packaging/dev-repo.sh [DIR] [package …]   DIR default ~/.local/share/bromigos/repo
#   bromigos channel dev [--dev-dir DIR]       then points pacman at it (SigLevel Optional)
#   bromigos update                            installs your build
#
# Every package in packaging/*/ (or the ones named) is built with makepkg from this
# checkout (pkgver() reads git, so a dirty tree still gets a sensible version) and added
# to DIR/bromigos/x86_64/bromigos.db with repo-add. Unsigned: it's your own machine's
# build; the published channels are signed by CI (packaging/ci/publish.sh).
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root=$(cd "$here/.." && pwd)
dir=${1:-$HOME/.local/share/bromigos/repo}; shift || true
repo=bromigos arch=x86_64
out="$dir/$repo/$arch"
mkdir -p "$out"
if (($#)); then names=("$@"); else
  names=(); for d in "$root"/packaging/*/; do [[ -f "$d/PKGBUILD" ]] && names+=("$(basename "$d")"); done
fi
export PKGDEST="$out"
built=()
for name in "${names[@]}"; do
  echo "== $name"
  ( cd "$root/packaging/$name" && makepkg --nodeps --noconfirm --force --clean )
  mapfile -t files < <(cd "$root/packaging/$name" && makepkg --packagelist)
  for f in "${files[@]}"; do [[ -f "$f" ]] && built+=("$f"); done
done
(( ${#built[@]} )) || { echo "dev-repo: nothing built" >&2; exit 1; }
repo-add --remove "$out/$repo.db.tar.gz" "${built[@]}"
echo "dev-repo: $out ($(ls "$out"/*.pkg.tar.* 2>/dev/null | wc -l) package files)"
echo "next: bromigos channel dev${1:+ --dev-dir $dir} && bromigos update"
