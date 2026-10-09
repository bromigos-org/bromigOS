-- bromigOS's plugin specs over LazyVim's: the theme, and a terminal-friendly UI.
return {
  { "LazyVim/LazyVim", opts = { colorscheme = "bromigos" } },
  -- the desktop's font is Geist Mono, not a Nerd Font: ASCII icons keep the UI aligned
  { "nvim-tree/nvim-web-devicons", enabled = false },
  { "nvim-mini/mini.icons", opts = { style = "ascii" } },
}
