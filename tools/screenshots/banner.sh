#!/bin/bash
# The terminal in the README's pictures: bromigOS's login banner (the emblem beside the
# readings, as `bromigos banner` prints them) with demo readings, then a short git
# session in the demo project. Run by the picture's kitty (bromigos_previews: the scene's
# "terminal" script); touches $PV_READY when everything is drawn.
cd "$HOME/projects/drift-atlas" || exit 1
P=$'\e[1;34m~/projects/drift-atlas\e[0m \e[35mmain\e[0m \e[32m❯\e[0m '
say() { printf '%s%s\n' "$P" "$1"; }
art=()
st=${XDG_STATE_HOME:-$HOME/.local/state}/bromigos
# the theme's emblem (a world's post has its own mark), as bromigos-banner finds it
for f in "$st/emblem/emblem.braille" "$st/theme/current/emblem/emblem.braille" \
         "$BROMIGOS_SHARE_DIR/themes/wick/emblem/emblem.braille"; do
  [[ -r $f ]] && { mapfile -t art <"$f"; break; }
done
L=$'\e[90m' V=$'\e[92m' H=$'\e[1;32m' R=$'\e[0m'
info=(
  ""
  "${H}drift${R}"
  ""
  "${L}KERNEL${R}  ${V}6.16.8-arch1-1${R}"
  "${L}UPTIME${R}  ${V}3d 4h 12m${R}"
  "${L}LOAD  ${R}  ${V}3.12 2.87 2.41${R} ${L}on 24 cores${R}"
  "${L}MEMORY${R}  ${V}37%${R} ${L}of 64 GiB${R}"
  "${L}DISK /${R}  ${V}38%${R} ${L}of 1.8T${R}"
  "${L}DISK /home${R}  ${V}61%${R} ${L}of 1.8T${R}"
)
say "bromigos banner"
n=$(( ${#art[@]} > ${#info[@]} ? ${#art[@]} : ${#info[@]} ))
printf '\n'
for (( i = 0; i < n; i++ )); do
  a=${art[i]:-}
  plain=$(printf '%s' "$a" | sed 's/\x1b\[[0-9;]*m//g')
  printf '  %s%*s   %s\n' "$a" $(( 22 - ${#plain} )) "" "${info[i]:-}"
done
printf '\n'
say "git log --oneline --graph -4"; git -c color.ui=always log --oneline --graph --decorate -4
say "git status -sb"; git -c color.ui=always status -sb
printf '%s' "$P"
touch "$PV_READY"
exec sleep 300
