# bromigOS Server's welcome tour (bromigos welcome-console; docs/iso.md, "Editions"), once,
# at the first sign-in on its console or over SSH: only on a computer that starts to the text
# console, only in an interactive terminal, and only while the installer's marker is there.
case $- in *i*) ;; *) return 0 2>/dev/null ;; esac
if [ -t 0 ] && [ -z "${WAYLAND_DISPLAY:-}${DISPLAY:-}" ] &&
   [ -e "${XDG_STATE_HOME:-$HOME/.local/state}/bromigos/welcome-pending" ] &&
   [ "$(systemctl get-default 2>/dev/null)" = "multi-user.target" ] &&
   [ -x /usr/lib/bromigos/bin/bromigos-welcome-console ]; then
    /usr/lib/bromigos/bin/bromigos-welcome-console --if-pending
fi
