-- Print the binds a Hyprland Lua config makes, without Hyprland: runs the config with a
-- stand-in `hl` that does nothing, then prints the list bromigos/keys.lua kept (K.dump()).
-- Used by keybinds.py when Hyprland can't be asked, and by `bromigos-docs keys`.
--
--   lua keybinds-dump.lua ~/.config/hypr/hyprland.lua

local path = arg[1] or (os.getenv("HOME") .. "/.config/hypr/hyprland.lua")
local dir = path:match("^(.*)/[^/]*$") or "."
package.path = dir .. "/?.lua;" .. dir .. "/?/init.lua;" .. package.path

-- Anything: callable, indexable, returns more of itself (hl.dsp.window.close() etc.).
local function stub()
    return setmetatable({}, {
        __index = function() return stub() end,
        __call = function() return stub() end,
    })
end
hl = stub()
hl.bind = function() return stub() end
-- queries (hl.get_monitors() …) answer with nothing: no outputs, no windows
setmetatable(hl, { __index = function(_, k)
    if type(k) == "string" and k:sub(1, 4) == "get_" then return function() return {} end end
    return stub()
end })

local real_print = print
print = function() end -- the config's own log lines aren't part of the list
dofile(path)
print = real_print

local keys = package.loaded["bromigos.keys"]
if keys then
    io.write(keys.dump(), "\n")
end
