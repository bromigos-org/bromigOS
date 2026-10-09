-- Keymaps over LazyVim's (lazyvim.org/keymaps). Few: LazyVim's set is the one documented.
local map = vim.keymap.set
map("n", "<leader>ut", function() vim.cmd.colorscheme("bromigos") end, { desc = "Re-apply the bromigOS theme" })
