# `bromigos update` reads snap-pac's pre/post pair as the user, to record the update for
# `bromigos update --rollback`; snapper answers "No permissions." unless its `root`
# configuration allows the user. `bromigos rollback setup` made that configuration without
# it until now (the ISO's installer always allowed wheel), so updates went unrecorded.
# This lets wheel list root's snapshots (and the user, when they aren't in wheel), with
# SYNC_ACL for /.snapshots: `bromigos rollback allow`, which keeps the groups and users
# already there and asks sudo on the terminal, like the update's other root steps.
# A machine where the user can list them already is left as it is.
set -u
if ! command -v snapper >/dev/null 2>&1 || [ ! -e /etc/snapper/configs/root ]; then
    echo "no snapper configuration for /: nothing to allow (bromigos rollback setup makes one, wheel allowed)"
    exit 0
fi
if snapper -c root --no-headers --csvout list --columns number >/dev/null 2>&1; then
    echo "$(id -un) may list root's snapshots already"
    exit 0
fi
if bromigos rollback allow; then
    exit 0
fi
echo "snapper's root configuration is unchanged (sudo didn't run?): the next update tries again, or run bromigos rollback allow" >&2
exit 75
