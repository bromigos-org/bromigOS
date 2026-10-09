#!/usr/bin/env bash
# Root setup in a fresh archlinux:base-devel container, before publish.sh:
# the tools publish.sh needs, and an unprivileged `builder` (makepkg refuses
# root) that may run pacman through sudo to install build dependencies.
# Usage: prepare-container.sh <checkout dir>
set -euo pipefail
checkout=${1:?usage: prepare-container.sh <checkout dir>}

pacman -Syu --noconfirm --needed git rclone >/dev/null
# uid 1001: the homelab runners' user, who owns the node cache (/ci-cache).
id builder >/dev/null 2>&1 || useradd --create-home --user-group --uid 1001 builder
echo 'builder ALL=(root) NOPASSWD: /usr/bin/pacman' > /etc/sudoers.d/builder
chmod 0440 /etc/sudoers.d/builder
# The checkout belongs to whoever ran actions/checkout; builder owns it now
# (pkgver() rewrites each PKGBUILD) and git must accept that.
chown -R builder:builder "$checkout"
git config --system --add safe.directory "$checkout"

# ── cargo's cache, on a homelab runner ───────────────────────────────────────
# The workflow binds the node's cache (/ci-cache, homelab helm/arc-runners) when
# it runs on a homelab runner. cargo's registry and bromigos-core's release
# target directory live there, so a rebuild compiles only what changed (cargo
# locks both against a concurrent run). Elsewhere (GitHub's runners) nothing is
# set and each build starts clean.
cache=/ci-cache/cargo
if [[ -d /ci-cache && -n "${GITHUB_ENV:-}" ]]; then
  mkdir -p "$cache/home" "$cache/target/bromigos-core"
  # Past 6 GiB the target directory is mostly stale artifacts: start it over.
  used=$(du -sk "$cache/target" 2>/dev/null | cut -f1 || echo 0)
  if (( used > 6 * 1024 * 1024 )); then
    echo "prepare: cargo target cache at $((used / 1024)) MiB; clearing it"
    find "$cache/target" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
    mkdir -p "$cache/target/bromigos-core"
  fi
  chown builder:builder "$cache" "$cache/home" "$cache/target" "$cache/target/bromigos-core"
  {
    echo "CARGO_HOME=$cache/home"
    echo "BROMIGOS_CARGO_TARGET_DIR=$cache/target/bromigos-core"
  } >> "$GITHUB_ENV"
  echo "prepare: cargo cache at $cache ($(du -sh "$cache" 2>/dev/null | cut -f1))"
fi
