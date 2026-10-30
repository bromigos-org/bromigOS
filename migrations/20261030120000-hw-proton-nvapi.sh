# Proton games on NVIDIA's own driver now get NVAPI, for DLSS and Reflex: the session's GPU
# environment, ~/.local/state/bromigos/hw/hyprland.lua, sets PROTON_ENABLE_NVAPI=1 while
# NVIDIA's kernel module is loaded (docs/hardware.md). This writes that file again with
# `bromigos hw setup --user-only`: no sudo, no packages, and a file of your own stays as it
# is. It takes effect at your next login. Other GPUs get the same file without the variable.
set -u
command -v bromigos >/dev/null 2>&1 || { echo "bromigos isn't installed yet"; exit 75; }
bromigos hw setup --user-only
