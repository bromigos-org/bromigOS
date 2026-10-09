# The live layer's animation switches (`bromigos anim on|off …`) moved from
# ~/.local/state/bromigos-live/overrides.toml to ~/.config/bromigos/live/overrides.toml:
# they're the user's choices, which belong with their settings, not generated state.
# Both readers already fall back to the old file; this moves it.
set -eu
old="$XDG_STATE_HOME/bromigos-live/overrides.toml"
new="$XDG_CONFIG_HOME/bromigos/live/overrides.toml"
if [ ! -e "$old" ]; then
    echo "nothing to move"
elif [ -e "$new" ]; then
    echo "kept $new; the old $old is no longer read"
else
    mkdir -p "${new%/*}"
    mv "$old" "$new"
    echo "moved $old -> $new"
fi
