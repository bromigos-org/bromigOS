# bromigOS's shell defaults (package bromigos-desktop): /usr/share/bromigos/default/zsh/bromigos.zsh.
# Source it from your .zshrc. Don't edit; updates replace it.
#
#   BROMIGOS_BANNER   login (default: interactive login shells only)
#                     always (every interactive shell) | off
#   bromigos banner   print it now

# A persistent multiplexer can start in a text console before the desktop exists.
# Its panes inherit that old environment even after a graphical client attaches.
# Refresh before commands, so an already-open shell also recovers after login.
# Use the core's session discovery; never eval its output or import it globally.
_bromigos_session_refresh() {
  [[ -o interactive && $BROMIGOS_SESSION_REFRESH != off ]] || return 0
  [[ $HERDR_ENV == 1 || -n $TMUX || -n $STY ]] || return 0
  [[ -z $SSH_CONNECTION && -z $SSH_CLIENT && -z $SSH_TTY ]] || return 0
  [[ $TERM != linux && $TERM != dumb && -n $XDG_RUNTIME_DIR ]] || return 0
  (( $+commands[bromigos] )) || return 0
  # The common path needs no child process, including an explicit nested display.
  if [[ -n $WAYLAND_DISPLAY ]]; then
    local socket=$WAYLAND_DISPLAY
    [[ $socket == /* ]] || socket=$XDG_RUNTIME_DIR/$socket
    [[ -S $socket ]] && return 0
  elif [[ -n $DISPLAY ]]; then
    return 0
  fi
  local entry key value
  while IFS= read -r entry; do
    key=${entry%%=*}
    value=${entry#*=}
    case $key in
      WAYLAND_DISPLAY|HYPRLAND_INSTANCE_SIGNATURE|DISPLAY|XAUTHORITY)
        if [[ $entry == *=* ]]; then
          if [[ -n $value ]]; then export "$key=$value"
          else unset "$key"
          fi
        fi ;;
    esac
  done < <(command bromigos session shell-env 2>/dev/null)
  return 0
}
if [[ -o interactive ]]; then
  autoload -Uz add-zsh-hook
  add-zsh-hook preexec _bromigos_session_refresh
  _bromigos_session_refresh
fi

# The banner: the theme's emblem beside live readings from /proc.
if [[ -o interactive && -t 1 && -z $NVIM && $BROMIGOS_BANNER != off ]]; then
  if [[ $BROMIGOS_BANNER == always || -o login ]]; then
    bromigos-banner
  fi
fi

# Frecent folders: `z <part>` jumps, `zi` picks with fzf. Its database also feeds the
# WORKBENCH desktop panel (bromigos-widgets), so the folders you actually use show up there.
(( $+commands[zoxide] )) && eval "$(zoxide init zsh)"

# Existing installs without shell.toml keep their own prompt.
if [[ -r ${XDG_CONFIG_HOME:-$HOME/.config}/bromigos/shell.toml && -z $_bromigos_prompt_loaded ]]; then
  typeset -g _bromigos_prompt_loaded=1
  # The config parser prints a validated engine name, never evaluated config text.
  local _bromigos_engine
  _bromigos_engine=$(python -c 'import os,pathlib,tomllib; p=pathlib.Path(os.environ.get("XDG_CONFIG_HOME") or pathlib.Path.home()/".config")/"bromigos/shell.toml"; v=tomllib.loads(p.read_text()).get("prompt","none"); print(v if v in ("mehshell","starship","none") else "none")' 2>/dev/null)
  case $_bromigos_engine in
    mehshell) export MEHSHELL_BROMIGOS=1
      (( $+commands[mehshell] )) && eval "$(mehshell init zsh)" ;;
    starship) (( $+commands[starship] )) && eval "$(starship init zsh)" ;;
    none) PROMPT='%~ %# '; RPROMPT='' ;;
  esac
  unset _bromigos_engine
fi
