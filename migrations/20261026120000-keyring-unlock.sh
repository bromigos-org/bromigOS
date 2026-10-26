# Sign-ins (bromigos login, bromigos account, the widgets' accounts) are kept in the login
# keyring. bromigos-desktop now brings one, oo7, and starts it in every session; this makes
# the login unlock it with your password, so nothing asks: `bromigos keyring setup` adds
# oo7's lines to /etc/pam.d/login (a text console login), sddm (the login screen) and
# passwd (a new password carries over), asking sudo on the terminal like the update's other
# root steps, and turns KWallet's own Secret Service off in ~/.config/kwalletrc, so oo7
# alone answers for the keyring. Lines a user added by hand (gnome-keyring's, or oo7's own)
# stay as they are, and a file that has oo7's lines already isn't touched.
# With no terminal it uses sudo only when sudo needs no password (the ISO's installer).
# oo7 not installed yet, or sudo didn't run: exit 75, and the next update tries again.
set -u
if ! pacman -Qq bromigos-desktop >/dev/null 2>&1; then
    echo "no bromigOS desktop here: nothing to unlock (bromigos keyring setup sets it up any time)"
    exit 0
fi
bromigos keyring setup
rc=$?
if [ "$rc" -eq 0 ]; then
    echo "your keyring is unlocked by your login from your next sign-in: sign out and in again"
fi
exit "$rc"
