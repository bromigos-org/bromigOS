-- `:colorscheme bromigos`: the current bromigOS theme, rendered by `bromigos theme set` into
-- ~/.local/state/bromigos/theme/current/nvim.lua (docs/theming.md, "Templates"). While this
-- colorscheme is on, the file is watched (every 2 s, its mtime) and re-applied when a theme
-- switch rewrites it, so neovim follows the desktop without a restart.
local state = os.getenv("XDG_STATE_HOME")
if state == nil or state == "" then state = os.getenv("HOME") .. "/.local/state" end
local path = state .. "/bromigos/theme/current/nvim.lua"

local function apply()
  local ok, err = pcall(dofile, path)
  if not ok then
    vim.notify("bromigOS theme: " .. tostring(err), vim.log.levels.WARN)
    vim.cmd.colorscheme("habamax")      -- neovim's own fallback: something readable
    return false
  end
  return true
end

local function mtime()
  local st = (vim.uv or vim.loop).fs_stat(path)
  return st and st.mtime.sec or 0
end

vim.cmd("highlight clear")
if vim.fn.exists("syntax_on") == 1 then vim.cmd("syntax reset") end
if apply() then
  local seen = mtime()
  if _G.__bromigos_theme_timer then _G.__bromigos_theme_timer:stop() end
  local timer = (vim.uv or vim.loop).new_timer()
  _G.__bromigos_theme_timer = timer
  timer:start(2000, 2000, vim.schedule_wrap(function()
    if vim.g.colors_name ~= "bromigos" then
      timer:stop()                        -- the user chose another scheme: stop watching
      return
    end
    local now = mtime()
    if now ~= seen then
      seen = now
      apply()
    end
  end))
end
