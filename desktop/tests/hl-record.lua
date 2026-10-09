-- Runs a Hyprland Lua config with a stand-in `hl` that records what it configures for
-- input devices and keys, one line each (tab-separated), without Hyprland:
--   device  <name>  <tags>  <kb_options>
--   bind    <keys>  <release|>  <device list: "tag,…", "!tag,…" = all but>  <what it runs>
-- Used by test_peripherals_lua.py, and to compare a user's binds before and after a change.
--
--   lua hl-record.lua ~/.config/hypr/hyprland.lua

local path = arg[1] or (os.getenv("HOME") .. "/.config/hypr/hyprland.lua")
local dir = path:match("^(.*)/[^/]*$") or "."
package.path = dir .. "/?.lua;" .. dir .. "/?/init.lua;" .. package.path

local function stub()
    return setmetatable({}, {
        __index = function() return stub() end,
        __call = function() return stub() end,
    })
end
local out = {}
hl = setmetatable({}, { __index = function(_, k)
    if type(k) == "string" and k:sub(1, 4) == "get_" then return function() return {} end end
    return stub()
end })
hl.get_config = function() return os.getenv("KB_OPTIONS") or "" end
hl.device = function(spec)
    out[#out + 1] = table.concat({ "device", spec.name or "", spec.tags or "", spec.kb_options or "" }, "\t")
end
hl.bind = function(keys, _, opts)
    opts = opts or {}
    local dev = ""
    if opts.device then
        dev = (opts.device.inclusive == false and "!" or "") .. table.concat(opts.device.list or {}, ",")
    end
    local what = (opts.description or ""):match('^hl%.dsp%.exec_cmd%((.*)%)$') or opts.description or ""
    out[#out + 1] = table.concat({ "bind", keys, opts.release and "release" or "", dev, what }, "\t")
    return stub()
end

local real_print = print
print = function() end
dofile(path)
print = real_print
io.write(table.concat(out, "\n"), "\n")
