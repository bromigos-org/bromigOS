# The start page is packaged (bromigos-desktop): /usr/share/bromigos/startpage, kept in a
# self-contained folder per user (~/.local/share/bromigos/startpage) by the packaged
# snapshot and its timer. This enables that timer and fills the folder once. A user's own
# unit of the same name in ~/.config/systemd/user (an old dotfiles copy) is left alone:
# systemd prefers it, so this waits (exit 75: not yet) until it's removed.
set -eu
[ -x /usr/lib/bromigos/desktop/startpage/snapshot.py ] || {
    echo "bromigos-desktop doesn't ship the start page yet"
    exit 75
}
user_unit="$XDG_CONFIG_HOME/systemd/user/bromigos-startpage.service"
if [ -e "$user_unit" ] && ! grep -q '/usr/lib/bromigos/desktop/startpage/snapshot.py' "$user_unit"; then
    # an old copy (e.g. from dotfiles) overrides the packaged unit: wait until it's gone
    echo "your own $user_unit overrides bromigOS's; remove it and the next update enables the packaged timer"
    exit 75
else
    systemctl --user daemon-reload 2>/dev/null || true
    systemctl --user enable --now bromigos-startpage.timer 2>/dev/null \
        && echo "enabled bromigos-startpage.timer" \
        || echo "couldn't enable bromigos-startpage.timer now (no user session?); the next update tries again"
fi
/usr/lib/bromigos/desktop/startpage/snapshot.py \
    && echo "the start page: ${BROMIGOS_STARTPAGE_DIR:-$HOME/.local/share/bromigos/startpage}/index.html"
