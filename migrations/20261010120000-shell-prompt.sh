# Seed the prompt only when there is no zsh startup file. Existing installs keep theirs.
set -eu
config=${XDG_CONFIG_HOME:-$HOME/.config}
if [ ! -e "$HOME/.zshrc" ] && [ ! -e "${ZDOTDIR:-$HOME}/.zshrc" ]; then
    mkdir -p "$config/bromigos"
    if [ ! -e "$config/bromigos/shell.toml" ]; then
        printf '# bromigOS zsh prompt\nprompt = "mehshell"\n' > "$config/bromigos/shell.toml"
    fi
    mkdir -p "${ZDOTDIR:-$HOME}"
    printf 'source /usr/share/bromigos/default/zsh/bromigos.zsh\n' > "${ZDOTDIR:-$HOME}/.zshrc"
fi
