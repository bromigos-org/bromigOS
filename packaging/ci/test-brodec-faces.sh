#!/usr/bin/env bash
# Tests for brodec-faces.sh against a stand-in BRODEC repository (a file:// one): a staged
# release passes, and each thing fetch must refuse is refused. No network, no bucket.
#
#   packaging/ci/test-brodec-faces.sh
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
script=$here/brodec-faces.sh
t=$(mktemp -d)
trap 'rm -rf "$t"' EXIT
export GIT_AUTHOR_NAME=test GIT_AUTHOR_EMAIL=test@example.org GIT_COMMITTER_NAME=test GIT_COMMITTER_EMAIL=test@example.org
fails=0
ok() { echo "ok - $*"; }
bad() { echo "FAIL - $*"; fails=$((fails + 1)); }

git init -q --bare "$t/brodec.git"
git clone -q "$t/brodec.git" "$t/src" 2>/dev/null
git -C "$t/src" commit -q --allow-empty -m "main"
git -C "$t/src" push -q origin HEAD:refs/heads/main
on_main=$(git -C "$t/src" rev-parse HEAD)
git -C "$t/src" checkout -q -b side
git -C "$t/src" commit -q --allow-empty -m "not on main"
off_main=$(git -C "$t/src" rev-parse HEAD)
git -C "$t/src" push -q origin side

# make DIR [extra zip entry]: a release of version 1.0.7 (100000007) in DIR, as stage.sh leaves it.
make() {
  local d=$1 extra=${2:-}
  rm -rf "$d"; mkdir -p "$d/1.0.7"
  python3 -I - "$d" "$extra" <<'PY'
import hashlib, json, os, sys, zipfile
d, extra = sys.argv[1], sys.argv[2]
apk = os.path.join(d, "1.0.7", "cuff.apk")
with zipfile.ZipFile(apk, "w") as z:
    z.writestr("AndroidManifest.xml", b"\x03\x00manifest")
    z.writestr("resources.arsc", b"arsc")
    z.writestr("res/raw/watchface.xml", b"<WatchFace/>")
    z.writestr("META-INF/MANIFEST.MF", b"Manifest-Version: 1.0\n")
    if extra: z.writestr(extra, b"x")
data = open(apk, "rb").read()
open(os.path.join(d, "1.0.7", "cuff.token"), "w").write("tok\n")
json.dump({"schema": 1, "faces": [{
    "id": "cuff", "name": "THE CUFF", "package": "org.bromigos.brodec.watchfacepush.cuff",
    "versionCode": 100000007, "versionName": "1.0.7", "layouts": ["OPS HUD"],
    "apk": "1.0.7/cuff.apk", "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
    "token": "tok", "minSdk": 36}]}, open(os.path.join(d, "latest.json"), "w"))
PY
}

# stage DIR SOURCE: DIR as the only content of a parentless commit at the ref.
stage() {
  local d=$1 source=$2 idx=$t/index
  rm -f "$idx"
  while IFS= read -r f; do
    blob=$(git -C "$t/src" hash-object -w "$d/$f")
    GIT_INDEX_FILE=$idx git -C "$t/src" update-index --add --cacheinfo "100644,$blob,$f"
  done < <(cd "$d" && find . -type f | sed 's|^\./||' | LC_ALL=C sort)
  tree=$(GIT_INDEX_FILE=$idx git -C "$t/src" write-tree)
  msg=$(printf 'brodec-faces 1.0.7\n\nsource: %s\nversion: 1.0.7\nversionCode: 100000007\nmanifest-sha256: %s\n' \
    "$source" "$(sha256sum "$d/latest.json" | cut -d' ' -f1)")
  c=$(git -C "$t/src" commit-tree "$tree" -m "$msg")
  git -C "$t/src" push -q -f origin "$c:refs/brodec-faces/build"
}

export BRODEC_GIT_URL=file://$t/brodec.git
run() { "$script" "$@" > "$t/out" 2>&1; }

make "$t/good"
stage "$t/good" "$on_main"
run staged && grep -qx 'version_code=100000007' "$t/out" && ok "staged reads the version" || bad "staged: $(cat "$t/out")"
run fetch "$t/f1" && [[ -f $t/f1/.checked && -f $t/f1/1.0.7/cuff.apk ]] && ok "a good release is checked" || bad "fetch: $(cat "$t/out")"

mkdir -p "$t/pub/brodec/faces"
export PKGS_PUBLIC_URL=file://$t/pub
run missing 100000007 && grep -qx 'publish=true' "$t/out" && ok "nothing published: publish" || bad "missing (none): $(cat "$t/out")"
cp "$t/good/latest.json" "$t/pub/brodec/faces/latest.json"
run missing 100000007 && grep -qx 'publish=false' "$t/out" && ok "the same version published: nothing to do" || bad "missing (same): $(cat "$t/out")"
run missing 100000008 && grep -qx 'publish=true' "$t/out" && ok "a newer one: publish" || bad "missing (newer): $(cat "$t/out")"

refused() {   # refused WHAT DIR SOURCE
  stage "$2" "$3"
  if run fetch "$t/f-$RANDOM"; then bad "$1 was accepted"; else ok "$1 is refused ($(tail -1 "$t/out"))"; fi
}
make "$t/code" classes.dex
refused "an APK with code" "$t/code" "$on_main"
make "$t/sum"; printf 'x' >> "$t/sum/1.0.7/cuff.apk"
refused "an APK that isn't the one latest.json describes" "$t/sum" "$on_main"
make "$t/extra"; echo hi > "$t/extra/1.0.7/notes.txt"
refused "a commit with other files" "$t/extra" "$on_main"
make "$t/tok"; echo other > "$t/tok/1.0.7/cuff.token"
refused "a token that isn't latest.json's" "$t/tok" "$on_main"
make "$t/pkg"; sed -i 's/org.bromigos.brodec.watchfacepush.cuff/com.example.watchfacepush.cuff/' "$t/pkg/latest.json"
refused "another app's package" "$t/pkg" "$on_main"
make "$t/side"
refused "a build from a commit that isn't on main" "$t/side" "$off_main"

if (( fails )); then echo "$fails failed"; exit 1; fi
echo "all passed"
