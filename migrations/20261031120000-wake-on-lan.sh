# Wake-on-LAN stays on for wired network cards (docs/wake-on-lan.md): bromigos-core now ships
# NetworkManager's default (ethernet.wake-on-lan magic) and a udev rule that turns it on for
# each wired card at every start, and its install step turned it on for the cards already
# there. This checks that it took: `bromigos wol status`. When a wired card still
# has it off (the package was installed where it couldn't reach the cards, an installer's
# chroot), it turns it on with sudo, only when sudo needs no password; otherwise the next
# start does it anyway. A machine without a wired card has nothing to do. No questions.
set -u
command -v bromigos >/dev/null 2>&1 || { echo "bromigos isn't installed yet"; exit 75; }
helper=${BROMIGOS_WOL_HELPER:-/usr/lib/bromigos/bin/bromigos-wol}   # tests: a stand-in
[ -x "$helper" ] || { echo "bromigos-core with Wake-on-LAN isn't installed yet"; exit 75; }
state=$("$helper" status --json 2>/dev/null) || state=
if [ -z "$state" ]; then
    echo "couldn't read Wake-on-LAN here; it's on from the next start"
    exit 0
fi
off=$(printf '%s' "$state" | python3 -c 'import json,sys; s=json.load(sys.stdin); print(" ".join(c["name"] for c in s["cards"] if c.get("on") is False and not s["opted_out"]))' 2>/dev/null || true)
if [ -z "$off" ]; then
    echo "Wake-on-LAN: kept on for the wired cards here (or there are none)"
    exit 0
fi
if sudo -n true 2>/dev/null; then
    # shellcheck disable=SC2086
    sudo -n "$helper" apply --quiet $off || true
    echo "Wake-on-LAN turned on for: $off"
else
    echo "Wake-on-LAN is still off for: $off; it turns on at the next start"
fi
exit 0
