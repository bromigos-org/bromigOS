# bromigOS's shell defaults (package bromigos-desktop): /usr/share/bromigos/default/zsh/bromigos.zsh.
# Source it from your .zshrc. Don't edit; updates replace it.
#
#   BROMIGOS_BANNER   login (default: interactive login shells only)
#                     always (every interactive shell) | off
#   bromigos banner   print it now

# The banner: the theme's emblem beside live readings from /proc.
if [[ -o interactive && -t 1 && -z $NVIM && $BROMIGOS_BANNER != off ]]; then
  if [[ $BROMIGOS_BANNER == always || -o login ]]; then
    bromigos-banner
  fi
fi

# Frecent folders: `z <part>` jumps, `zi` picks with fzf. Its database also feeds the
# WORKBENCH desktop panel (bromigos-widgets), so the folders you actually use show up there.
(( $+commands[zoxide] )) && eval "$(zoxide init zsh)"
