# The public repository's address is https://pkgs.bromigos.org (docs/public.md). The first
# v0.1.2 ISO named the bucket's r2.dev address instead, which Cloudflare rate-limits and
# which will be turned off once machines have moved. This moves a machine's [bromigos]
# Server line from it to the same channel's path at pkgs.bromigos.org. Only a line that is
# exactly the r2.dev address, on stable, rc or edge, is rewritten; any other is left alone.
# /etc/pacman.conf is copied to /etc/pacman.conf.bromigos-r2dev first, and the new one put
# in place with `sudo install`, which asks on the terminal like the update's other root
# steps. The base `bromigos channel set` goes back to from dev moves the same way.
set -u
old=https://pub-725f58eecf5c43748779ba6473eb9720.r2.dev
new=https://pkgs.bromigos.org
conf=${BROMIGOS_PACMAN_CONF:-/etc/pacman.conf}
backup=$conf.bromigos-r2dev
state=${XDG_STATE_HOME:-$HOME/.local/state}/bromigos/channel.toml

# the remembered base: the user's own file
if [ -f "$state" ] && grep -qxF "base = \"$old\"" "$state"; then
    tmp=$(mktemp) || exit 75
    sed "s|^base = \"$old\"\$|base = \"$new\"|" "$state" > "$tmp" && cat "$tmp" > "$state"
    rm -f "$tmp"
    echo "the base bromigos channel set goes back to: $new"
fi

[ -r "$conf" ] || { echo "no $conf: nothing to move"; exit 0; }
tmp=$(mktemp) || exit 75
trap 'rm -f "$tmp"' EXIT
# in [bromigos] only, a Server line that is exactly the old address on a channel's path
if ! awk -v old="Server = $old" -v new="Server = $new" '
    /^\[/ { sect = $0 }
    sect == "[bromigos]" && ($0 == old "/$repo/$arch" || $0 == old "/$repo/stable/$arch" || $0 == old "/$repo/rc/$arch") {
        $0 = new substr($0, length(old) + 1); n++
    }
    { print }
    END { exit n ? 0 : 1 }' "$conf" > "$tmp"; then
    echo "the repository isn't at $old: nothing to move"
    exit 0
fi
if [ ! -e "$backup" ] && ! sudo cp -p "$conf" "$backup"; then
    echo "$conf is unchanged (sudo didn't run?): the next update tries again" >&2
    exit 75
fi
if ! sudo install -m 644 -o root -g root "$tmp" "$conf"; then
    echo "$conf is unchanged (sudo didn't run?): the next update tries again" >&2
    exit 75
fi
echo "the repository is $new now ($(grep -A2 -x '\[bromigos\]' "$conf" | grep '^Server' | head -1)); the old file is $backup"
