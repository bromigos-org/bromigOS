# The desktop's configs are bromigOS's defaults now (package bromigos-desktop,
# /usr/share/bromigos/default). The user's ~/.config holds thin files that include or
# import them and add their own (docs/desktop.md). This puts those thin files in place
# where the user has none: an existing file is the user's and is never touched (it's
# reported instead). Runs again on a later update until bromigos-desktop is installed.
set -eu
defaults="$BROMIGOS_SHARE_DIR/default"
user="$defaults/user"
[ -d "$user" ] || {
    echo "bromigos-desktop isn't installed yet"
    exit 75
}
C=$XDG_CONFIG_HOME

seed() { # seed <relative path>: copy the thin file unless there's one (or a link) already
    local dst="$C/$1"
    if [ -e "$dst" ] || [ -L "$dst" ]; then
        if grep -qs "/usr/share/bromigos/default\|$defaults" "$dst"; then
            echo "kept $dst (uses the defaults)"
        else
            echo "kept $dst (yours; it doesn't use bromigOS's defaults: see docs/desktop.md)"
        fi
        return
    fi
    mkdir -p "${dst%/*}"
    cp -- "$user/$1" "$dst"
    echo "made $dst"
}

render() { # render <relative path>: a file that names absolute paths, made from <path>.in
    local dst="$C/$1"
    if [ -e "$dst" ] || [ -L "$dst" ]; then
        echo "kept $dst"
        return
    fi
    mkdir -p "${dst%/*}"
    sed -e "s#@CONFIG@#$C#g" -e "s#@STATE@#$XDG_STATE_HOME#g" "$defaults/$1.in" > "$dst"
    echo "made $dst"
}

link() { # link <relative path> <target>
    local dst="$C/$1"
    if [ -e "$dst" ] || [ -L "$dst" ]; then
        echo "kept $dst"
        return
    fi
    mkdir -p "${dst%/*}"
    ln -s -- "$2" "$dst"
    echo "linked $dst -> $2"
}

seed hypr/hyprland.lua
seed hypr/hypridle.conf
seed hypr/hyprlock.conf
seed waybar/config
seed waybar/style.css
seed rofi/config.rasi
seed gtklock/style.css
render gtklock/config.ini
render gtklock/layout.ui
# dunst: the base config links to the default; the theme's colours and the user's own
# settings are drop-ins beside it. A user who has a dunstrc already keeps their own setup.
if [ -e "$C/dunst/dunstrc" ] || [ -L "$C/dunst/dunstrc" ]; then
    echo "kept $C/dunst/dunstrc"
else
    link dunst/dunstrc "$defaults/dunst/dunstrc"
    link dunst/dunstrc.d/90-bromigos-theme.conf "$XDG_STATE_HOME/bromigos/theme/current/dunst.conf"
    seed dunst/dunstrc.d/99-mine.conf
fi

# The shell: bromigOS doesn't edit a user's shell startup file; it says how.
if [ -f "$HOME/.zshrc" ] && ! grep -qs 'bromigos/default/zsh/bromigos.zsh\|zsh-bromigos' "$HOME/.zshrc"; then
    echo "for the login banner and zoxide, add to ~/.zshrc: source $defaults/zsh/bromigos.zsh"
fi
