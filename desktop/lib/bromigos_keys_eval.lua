-- What a user's Hyprland Lua config binds, and where each bind comes from, without
-- Hyprland: runs the config with a stand-in `hl` (as widgets/keybinds-dump.lua does) and
-- prints one line per fact, tab-separated, for `bromigos keys` (lib/bromigos_keys.py):
--
--   unbind   <keys>                                       bromigos.unbind as the defaults saw it
--   default  <release> <mouse> <keys> <kind> <payload>    a bind bromigOS's defaults make (also
--                                                         one bromigos.unbind turns off)
--   user     <release> <mouse> <keys> <kind> <payload>    a bind made after them (the user's
--                                                         own, the generated blocks, modules)
--   plain    <keys>                                       a bind made with hl.bind directly
--                                                         (not through bromigos.keys)
--   exclusive <keys>                                      a key a peripheral module keeps for its
--                                                         keyboard (K.exclude): binds on it must
--                                                         spell it this way to get the exclusion
--   error    <message>                                    the config stopped with this error
--
-- kind is exec (a shell command) or lua (dispatcher source), as bromigos/keys.lua keeps them;
-- \, tab and newline in a payload are escaped as \\ \t \n. Binds inside a submap are left
-- out: they aren't the desktop's keys.
--
--   lua bromigos_keys_eval.lua ~/.config/hypr/hyprland.lua

local path = arg[1] or ((os.getenv("HOME") or "") .. "/.config/hypr/hyprland.lua")
local dir = path:match("^(.*)/[^/]*$") or "."
package.path = dir .. "/?.lua;" .. dir .. "/?/init.lua;" .. package.path

local out = {}
local function emit(...)
    local f = { ... }
    for i, v in ipairs(f) do
        f[i] = tostring(v):gsub("\\", "\\\\"):gsub("\t", "\\t"):gsub("\n", "\\n")
    end
    out[#out + 1] = table.concat(f, "\t")
end

-- Anything: callable, indexable, returns more of itself (hl.dsp.window.close() etc.).
local function stub()
    return setmetatable({}, {
        __index = function() return stub() end,
        __call = function() return stub() end,
    })
end

local submap = nil          -- inside hl.define_submap(name, fn)
local seen = 0              -- #K.binds at the last hl.bind
local plain = {}
hl = setmetatable({}, { __index = function(_, k)
    if type(k) == "string" and k:sub(1, 4) == "get_" then return function() return {} end end
    return stub()
end })
hl.bind = function(keys)
    local K = package.loaded["bromigos.keys"]
    local n = (type(K) == "table" and type(K.binds) == "table") and #K.binds or 0
    if n == seen and submap == nil then
        plain[#plain + 1] = keys       -- no new entry in K.binds: not made through K
    end
    seen = n
    return stub()
end
hl.define_submap = function(name, a, b)
    local fn = type(a) == "function" and a or b
    local was = submap
    submap = name
    if type(fn) == "function" then pcall(fn) end
    submap = was
    local K = package.loaded["bromigos.keys"]
    if type(K) == "table" and type(K.binds) == "table" then
        -- a K bind made inside a submap isn't one of the desktop's keys
        seen = #K.binds
    end
end

-- The defaults: everything they bind is recorded, also what bromigos.unbind turns off
-- (so a moved or turned-off default can be named and put back), and where they end.
local real_dofile = dofile
local first, last = nil, nil
dofile = function(p, ...)
    if type(p) ~= "string" or not p:match("/default/hypr/hyprland%.lua$") or first ~= nil then
        return real_dofile(p, ...)
    end
    local B = type(bromigos) == "table" and bromigos or nil
    local saved = B and B.unbind
    for _, keys in ipairs(type(saved) == "table" and saved or {}) do
        emit("unbind", keys)
    end
    if B then B.unbind = nil end
    local K0 = package.loaded["bromigos.keys"]
    local skip0 = K0 and K0.skip
    if K0 then K0.skip = {} end
    first = K0 and #K0.binds or 0
    local r = table.pack(pcall(real_dofile, p, ...))
    if B then B.unbind = saved end
    local K = package.loaded["bromigos.keys"]
    last = K and #K.binds or 0
    if K and K0 then K.skip = skip0 end
    if not r[1] then error(r[2], 0) end
    return table.unpack(r, 2, r.n)
end

local real_print = print
print = function() end   -- the config's own log lines aren't part of the list
local ok, err = pcall(real_dofile, path)
print = real_print
if not ok then
    emit("error", err)
end

local K = package.loaded["bromigos.keys"]
if type(K) == "table" and type(K.binds) == "table" then
    for i, b in ipairs(K.binds) do
        local where = (first ~= nil and i > first and i <= (last or first)) and "default" or "user"
        emit(where, b.release and "1" or "0", b.mouse and "1" or "0", b.keys, b.kind, b.payload)
    end
end
for _, keys in ipairs(plain) do
    emit("plain", keys)
end
if type(K) == "table" and type(K.exclusive) == "table" then
    for keys in pairs(K.exclusive) do
        emit("exclusive", keys)
    end
end
io.write(table.concat(out, "\n"), "\n")
