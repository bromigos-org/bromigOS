# bromigos-apps ships its app configs as read-only defaults; the user's side is thin files
# (neovim, tmux) or one-time copies (lazygit, mise, Chromium) that `bromigos apps setup`
# puts in place only where there's nothing yet (docs/apps.md). Runs it when the package is
# installed; without the package there's nothing to seed (run `bromigos apps setup` after
# installing it later).
set -eu
if [ ! -d "$BROMIGOS_SHARE_DIR/default/apps" ]; then
    echo "bromigos-apps isn't installed: nothing to seed (bromigos apps setup, after installing it)"
    exit 0
fi
exec "${BROMIGOS_LIB_DIR:-/usr/lib/bromigos}/bin/bromigos-apps-setup"
