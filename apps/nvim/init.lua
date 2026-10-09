-- bromigOS's neovim defaults: LazyVim (lazyvim.org) in the current theme's colours.
-- Package bromigos-apps installs this tree at /usr/share/bromigos/default/apps/nvim; a user's
-- ~/.config/nvim/init.lua (seeded by `bromigos apps setup`) puts it on the runtime path and
-- requires this file, then adds its own. Updates replace this tree, never ~/.config/nvim.
-- The approach is Omarchy's (its neovim is LazyVim, themed per Omarchy theme).
require("config.lazy")
