#!/usr/bin/env bash
# Runs once, inside the Field Kit image's chroot, at the end of mkarchiso's package step
# (iso/build.sh --edition fieldkit; docs/fieldkit.md).
set -euo pipefail

# the console: kmscon on the first console (true colour, Geist Mono, DRIFTGLASS); getty with
# bromigOS's colours and font where kmscon can't start (kmsconvt@'s OnFailure)
systemctl enable kmsconvt@tty1.service >/dev/null 2>&1
rm -f /etc/systemd/system/getty.target.wants/getty@tty1.service
# the apps bundle's terminal configs for root (LazyVim, tmux, lazygit), if bromigos-apps-terminal is here
[[ -x /usr/lib/bromigos/bin/bromigos-apps-setup ]] && HOME=/root /usr/lib/bromigos/bin/bromigos-apps-setup >/dev/null 2>&1 || true
# releng's root shell (zsh): bromigOS's prompt (mehshell), the toolbelt's keys and names
# (docs/fieldkit.md, "The toolbelt"): fzf on Ctrl+R (history), Ctrl+T (files) and Alt+C
# (folders) in DRIFTGLASS's colours, zoxide's z, eza for ls, bat for reading files
cat > /root/.zshrc <<'ZSH'
# bromigOS Field Kit's shell (iso/fieldkit/airootfs/root/customize_airootfs.sh)
export MEHSHELL_BROMIGOS=1 EDITOR=micro PAGER=less BAT_THEME=ansi
command -v mehshell >/dev/null && eval "$(mehshell init zsh)"
export FZF_DEFAULT_OPTS="--color=bg+:#003b00,fg:#c4f5bb,fg+:#e8ffe0,hl:#39ff14,hl+:#9cff8a,info:#7e927e,prompt:#39ff14,pointer:#39ff14,marker:#d4af37,spinner:#3fe0c5,header:#7e927e,border:#159b09 --border=rounded --height=50% --layout=reverse"
export FZF_DEFAULT_COMMAND="fd --type f --hidden --exclude .git"
command -v fzf >/dev/null && source <(fzf --zsh)
command -v zoxide >/dev/null && eval "$(zoxide init zsh)"
alias ls='eza --group-directories-first' ll='eza -l --group-directories-first --git' tree='eza --tree'
alias cat='bat --paging=never --style=plain' less='bat --paging=always'
HISTFILE=/root/.zsh_history HISTSIZE=10000 SAVEHIST=10000
ZSH
# tldr's pages, fetched now so `tldr` works offline on the medium
command -v tldr >/dev/null && { tldr --update >/dev/null 2>&1 || echo "customize_airootfs: tldr's pages couldn't be fetched (tldr works once online)"; }
# LazyVim's plugins, fetched now so Neovim works offline on the medium (as root, in its own data folder)
if command -v nvim >/dev/null && [[ -f /root/.config/nvim/init.lua ]]; then
    timeout 600 nvim --headless "+Lazy! sync" +qa >/dev/null 2>&1 || echo "customize_airootfs: LazyVim's plugins couldn't be fetched (Neovim works, plain)"
fi
# the editor: micro in DRIFTGLASS
install -d /root/.config/micro/colorschemes /root/.cache
ln -sf /usr/share/bromigos/fieldkit/micro/driftglass.micro /root/.config/micro/colorschemes/driftglass.micro
printf '{\n    "colorscheme": "driftglass",\n    "mkparents": true\n}\n' > /root/.config/micro/settings.json
# the offline store's databases, for pacman on the medium
pacman -Sy --noconfirm >/dev/null 2>&1 || true

# a test build only (iso/build.sh --test-key): the harness signs in as root over SSH
if [[ -s /etc/bromigos-iso/test_authorized_keys ]]; then
    install -d -m 700 /root/.ssh
    install -m 600 /etc/bromigos-iso/test_authorized_keys /root/.ssh/authorized_keys
    rm -f /etc/bromigos-iso/test_authorized_keys
    systemctl enable sshd.service >/dev/null 2>&1 || true
fi
echo "customize_airootfs: Field Kit is ready"
