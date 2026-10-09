# The idle policy became data (docs/idle.md): ~/.config/bromigos/idle.toml over the
# packaged defaults, rendered by `bromigos idle` into ~/.local/state/bromigos/idle/hypridle.conf.
# This points the user's ~/.config/hypr/hypridle.conf at that file: its line sourcing the
# packaged /usr/share/bromigos/default/hypr/hypridle.conf becomes one sourcing the rendered
# policy (the file is kept first in ~/.local/state/bromigos/idle/hypridle.conf.before-policy,
# and a dotfiles link is written through), and every other line, their own listeners, stays.
# A file that never sourced bromigOS's policy is the user's own setup: left alone, and named.
# Then `bromigos update`'s restarts start hypridle again on it (its config changed).
set -eu
command -v bromigos >/dev/null 2>&1 || { echo "bromigos isn't installed yet"; exit 75; }
bromigos idle hook
