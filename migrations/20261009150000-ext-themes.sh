# Themes used to be installed by copying them into ~/.config/bromigos/themes, without
# their git (so they never updated). Each one a catalog offers, file for file, becomes an
# extension: a checkout `bromigos ext update` updates, the old copy kept in
# ~/.local/state/bromigos/ext/adopted/ (docs/extensions.md). The others are left as they
# are; `bromigos ext list` names them. Offline or without the catalog: nothing changes,
# and `bromigos ext migrate` does it later.
set -u
if ! bromigos ext migrate; then
    echo "bromigos ext migrate didn't finish (offline, or the catalog unreachable): run it later"
fi
exit 0
