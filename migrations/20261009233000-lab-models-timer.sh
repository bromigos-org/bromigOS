# The lab model catalog's weekly check (bromigos-homelab, docs/lab-models.md): enables
# bromigos-lab-models.timer, which fetches the newest signed catalog and sends one quiet
# notification when a better model fits a lab GPU. It never installs anything, and it does
# nothing without a homelab configured. Turn it off with
# systemctl --user disable --now bromigos-lab-models.timer.
set -eu
[ -f /usr/lib/systemd/user/bromigos-lab-models.timer ] || {
    echo "bromigos-homelab doesn't ship the lab model catalog's timer yet (not installed, or older)"
    exit 75
}
systemctl --user daemon-reload 2>/dev/null || true
systemctl --user enable --now bromigos-lab-models.timer 2>/dev/null \
    && echo "enabled bromigos-lab-models.timer (weekly; a nudge when a better model fits)" \
    || { echo "couldn't enable bromigos-lab-models.timer now (no user session?); the next update tries again"; exit 75; }
