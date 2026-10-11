#!/usr/bin/env bash
# Shared by the signed-repository and pinned AUR recipes. No host configuration changes.
set -euo pipefail
root=${1:?source tree}
dest=${2:?package directory}
[[ $dest != / ]] || exit 2
lib="$dest/usr/lib/bromigos/lib/bromigos_homelab"
install -Dm0644 -t "$lib/" "$root"/homelab/lib/bromigos_homelab/*.py
install -Dm0644 -t "$lib/adapters/" "$root"/homelab/lib/bromigos_homelab/adapters/*.py
install -Dm0755 -t "$dest/usr/lib/bromigos/bin/" "$root"/homelab/bin/bromigos-{lab,homelab,setup-homelab,media}
install -d "$dest/usr/bin"
ln -s ../lib/bromigos/bin/bromigos-lab "$dest/usr/bin/bromigos-lab"
install -Dm0644 -t "$dest/usr/lib/systemd/user/" "$root"/homelab/systemd/*
for file in "$root"/homelab/share/lab/*.toml; do
  [[ ${file##*/} == models.toml ]] || install -Dm0644 -t "$dest/usr/share/bromigos/homelab/lab/" "$file"
done
# A separate fallback lets the desktop's independently updated catalog keep priority.
install -Dm0644 "$root/homelab/share/lab/models.toml" "$dest/usr/share/bromigos-lab/models.toml"
key_home=$(mktemp -d)
trap 'rm -rf "$key_home"' EXIT
GNUPGHOME="$key_home" gpg --batch --yes --dearmor --output "$dest/usr/share/bromigos-lab/bromigos.gpg" "$root/packaging/keys/bromigos.asc"
chmod 0644 "$dest/usr/share/bromigos-lab/bromigos.gpg"
install -Dm0644 "$root/homelab/share/homelab.toml" "$dest/usr/share/bromigos/default/homelab.toml"
install -Dm0644 -t "$dest/usr/share/doc/bromigos-lab/" "$root"/docs/{homelab,lab,lab-models,lab-provision,lab-infrastructure}.md
install -Dm0644 -t "$dest/usr/share/licenses/bromigos-lab/" "$root"/LICENSE-{MIT,APACHE}
python -m compileall -q -o 0 -o 1 -s "$dest" -p / "$lib"
