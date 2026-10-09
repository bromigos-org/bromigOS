-- lazy.nvim bootstrap plus the LazyVim distribution, as LazyVim's starter does it.
local lazypath = vim.fn.stdpath("data") .. "/lazy/lazy.nvim"
if not (vim.uv or vim.loop).fs_stat(lazypath) then
  local out = vim.fn.system({ "git", "clone", "--filter=blob:none", "--branch=stable",
    "https://github.com/folke/lazy.nvim.git", lazypath })
  if vim.v.shell_error ~= 0 then
    vim.api.nvim_echo({ { "lazy.nvim couldn't be cloned:\n", "ErrorMsg" }, { out, "WarningMsg" } }, true, {})
    vim.fn.getchar()
    os.exit(1)
  end
end
vim.opt.rtp:prepend(lazypath)

-- where these defaults live (/usr/share/bromigos/default/apps/nvim, or a checkout): lazy.nvim
-- resets the runtime path, so it's told to keep this one (the colorscheme and config.* are here)
local here = debug.getinfo(1, "S").source:sub(2):match("^(.*)/lua/config/lazy%.lua$") or vim.fn.stdpath("config")

require("lazy").setup({
  spec = {
    { "LazyVim/LazyVim", import = "lazyvim.plugins", opts = { colorscheme = "bromigos" } },
    { import = "plugins" },        -- bromigOS's lua/plugins, then the user's (both on the rtp)
  },
  defaults = { lazy = false, version = false },
  install = { colorscheme = { "bromigos", "habamax" } },
  checker = { enabled = false },   -- updates come with `bromigos update`, not on every start
  performance = {
    rtp = {
      paths = { here },
      disabled_plugins = { "gzip", "tarPlugin", "tohtml", "tutor", "zipPlugin" },
    },
  },
})
