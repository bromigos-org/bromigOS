-- My neovim: bromigOS's LazyVim defaults (package bromigos-apps), then mine.
-- Seeded by `bromigos apps setup`; this file is yours, updates never touch it.
local defaults = "/usr/share/bromigos/default/apps/nvim"
vim.opt.rtp:prepend(defaults)
dofile(defaults .. "/init.lua")
-- Mine: plugin specs in ~/.config/nvim/lua/plugins/*.lua (lazy.nvim imports them beside
-- bromigOS's), options and keymaps below.
