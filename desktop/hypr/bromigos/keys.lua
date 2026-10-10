-- Bind helpers for the bromigOS Hyprland config (required by binds.lua, live.lua and
-- vector.lua, and by the user's hyprland.lua for their own binds).
--
--   K.exec("ALT + E", "pcmanfm")                      run a shell command (sh -c: ~ and $HOME expand)
--   K.dsp("ALT + C", "hl.dsp.window.close()")         a dispatcher, written as Lua source
--   K.exec("SUPER + V", "... ptt off", { release = true })   opts are hl.bind's flags
--
-- The defaults' window keys pass { mod = true }: they're on bromigos.mod. While the
-- defaults bind (K.defaults), binds wait in a list, and K.finish() binds them all: a
-- window key and one of the desktop's own keys can't both have the same keys. With
-- mod = "SUPER", Super+L would both lock and move focus right. The window key keeps the
-- keys, and the desktop's key moves to Alt, which the window keys left (Super+L's lock to
-- Alt+L), or else to Super+Alt. `bromigos keys`, SHORTCUTS and the manual all read the
-- keys this leaves.
--
-- Each bind's action is also kept as text: in its `description` (so `hyprctl binds` says
-- what it does) and in the list K.dump() prints. That list is how the SHORTCUTS panel, the
-- rofi cheat sheet and `bromigos-docs keys` (widgets/keybinds.py) name and run every bind,
-- live with `hyprctl repl 'return package.loaded["bromigos.keys"].dump()'`, or from the
-- files with widgets/keybinds-dump.lua. `hyprctl binds -j` can't do it alone: a Lua bind's
-- dispatcher/arg there are "__lua" and a registry number, and a code:N bind shows an
-- empty key and keycode 0. A plain hl.bind() still works, but SHORTCUTS won't list it.

local M = { binds = {}, pending = {} }

-- Keys the user binds themselves (`bromigos.unbind = { "XF86AudioMicMute", ... }` in their
-- hyprland.lua, before the defaults run): a default bind on one of them is skipped, so it
-- isn't made twice and SHORTCUTS lists the user's own.
M.skip = {}
for _, keys in ipairs((type(bromigos) == "table" and bromigos.unbind) or {}) do
    M.skip[keys] = true
end
M.defaults = false   -- true while the bromigOS defaults are binding (only those can be skipped)

-- Keys whose binds ignore some devices: a peripheral module's keyboard can send a key the
-- default layout reads as another (a Razer side button as XF86AudioMicMute), so the
-- module's tag is excluded from that key's other binds (bromigos/peripherals.lua). A bind
-- that names its own devices keeps them.
M.exclusive = {}

--- Make every later bind on `keys` (made through these helpers) ignore devices tagged `tag`.
function M.exclude(keys, tag)
    local list = M.exclusive[keys] or {}
    table.insert(list, tag)
    M.exclusive[keys] = list
end

local function with_description(opts, text)
    local o = {}
    for k, v in pairs(opts or {}) do
        if k ~= "mod" and k ~= "submap" then          -- ours, not hl.bind's
            o[k] = v
        end
    end
    o.description = text
    return o
end

local function with_exclusions(keys, opts)
    local tags = M.exclusive[keys]
    if not tags or (opts and opts.device) then
        return opts
    end
    local o = {}
    for k, v in pairs(opts or {}) do
        o[k] = v
    end
    o.device = { inclusive = false, list = tags }
    return o
end

local function bind(b)
    local opts = b.opts
    table.insert(M.binds, { keys = b.keys, kind = b.kind, payload = b.payload,
                            release = opts.release and true or false, mouse = opts.mouse and true or false })
    local function make()
        return hl.bind(b.keys, b.dispatcher, with_description(with_exclusions(b.keys, opts), b.source))
    end
    if opts.submap then
        return hl.define_submap(opts.submap, make)
    end
    return make()
end

local function register(keys, kind, payload, source, dispatcher, opts)
    local b = { keys = keys, kind = kind, payload = payload, source = source, dispatcher = dispatcher,
                opts = opts or {} }
    if M.defaults then
        table.insert(M.pending, b)          -- bound by M.finish()
        return nil
    end
    return bind(b)
end

-- Keys as Hyprland compares them: the modifiers as a set (their other names folded in) and
-- the key without case ("SUPER + l" is "super + L").
local ALIAS = { WIN = "SUPER", LOGO = "SUPER", MOD4 = "SUPER", META = "SUPER", MOD1 = "ALT",
                CONTROL = "CTRL", CTL = "CTRL", SHFT = "SHIFT" }
local ORDER = { "SUPER", "ALT", "CTRL", "SHIFT" }

local function parse(keys)
    local parts = {}
    for p in keys:gmatch("[^+]+") do
        parts[#parts + 1] = p:match("^%s*(.-)%s*$")
    end
    local key = table.remove(parts) or ""
    local mods = {}
    for _, p in ipairs(parts) do
        local m = p:upper()
        mods[ALIAS[m] or m] = true
    end
    return mods, key
end

local function spell(mods, key)
    local out, seen = {}, {}
    for _, m in ipairs(ORDER) do
        if mods[m] then
            out[#out + 1] = m
            seen[m] = true
        end
    end
    local rest = {}
    for m in pairs(mods) do
        if not seen[m] then rest[#rest + 1] = m end
    end
    table.sort(rest)
    for _, m in ipairs(rest) do out[#out + 1] = m end
    out[#out + 1] = key
    return table.concat(out, " + ")
end

local function same(keys)
    local mods, key = parse(keys)
    return spell(mods, key:lower())
end

-- Where a desktop key goes when a window key has its keys: Alt instead of Super, then
-- Super+Alt (the modifiers it has, plus Alt).
local function elsewhere(keys)
    local mods, key = parse(keys)
    local out = {}
    if mods.SUPER then
        local m = {}
        for k in pairs(mods) do m[k] = true end
        m.SUPER, m.ALT = nil, true
        out[#out + 1] = spell(m, key)
    end
    local m = {}
    for k in pairs(mods) do m[k] = true end
    m.ALT = true
    if not mods.ALT then out[#out + 1] = spell(m, key) end
    return out
end

--- Bind the defaults (the defaults' hyprland.lua calls this after its binds): a desktop key
--- a window key (opts.mod) would share moves, every bind on it together (a hold key's press
--- and release); with nowhere free it's left out. Then the keys the user binds themselves
--- (bromigos.unbind) are skipped, by the keys the defaults end up on.
function M.finish()
    local pending = M.pending
    M.pending, M.defaults = {}, false
    local held, taken, moved = {}, {}, {}
    for _, b in ipairs(pending) do
        taken[same(b.keys)] = true
        if b.opts.mod then held[same(b.keys)] = true end
    end
    for _, b in ipairs(pending) do
        local k = same(b.keys)
        if not b.opts.mod and held[k] then
            if moved[k] == nil then
                moved[k] = false
                for _, alt in ipairs(elsewhere(b.keys)) do
                    if not taken[same(alt)] then
                        moved[k], taken[same(alt)] = alt, true
                        break
                    end
                end
                print(("bromigos: %s is a window key (mod = %s); its other bind went to %s")
                    :format(b.keys, tostring(type(bromigos) == "table" and bromigos.mod), moved[k] or "no key"))
            end
            b.keys = moved[k] or nil
        end
    end
    for _, b in ipairs(pending) do
        if b.keys and not M.skip[b.keys] then
            bind(b)
        end
    end
end

-- Build the dispatcher from its source. A mistake never stops the binds after it:
-- hl.bind reports it (hyprctl configerrors) and the log names the bind.
local function compile(keys, source)
    local chunk, err = load("return " .. source, "=bind " .. keys, "t")
    local ok, dispatcher = false, nil
    if chunk then
        ok, dispatcher = pcall(chunk)
        err = dispatcher
    end
    if not ok or dispatcher == nil then
        print(("bromigos bind %s -> %s: %s"):format(keys, source, tostring(err)))
        return nil
    end
    return dispatcher
end

--- Bind keys to a dispatcher written as Lua source, e.g. K.dsp("ALT + C", "hl.dsp.window.close()").
function M.dsp(keys, source, opts)
    return register(keys, "lua", source, source, compile(keys, source), opts)
end

--- Bind keys to a shell command.
function M.exec(keys, cmd, opts)
    if cmd:match("^bromigos%-live%s+tv%s+remote%s+") then
        local scoped = {}; for k, v in pairs(opts or {}) do scoped[k] = v end
        scoped.submap = "bromigos-tv-remote"; opts = scoped
    end
    local source = ("hl.dsp.exec_cmd(%q)"):format(cmd)
    return register(keys, "exec", cmd, source, compile(keys, source), opts)
end

--- Every bind made through these helpers, in order, one per line:
--- release<TAB>mouse<TAB>keys<TAB>kind<TAB>payload  (kind: exec = a shell command,
--- lua = dispatcher source; \ tab and newline in the payload are escaped as \\ \t \n).
function M.dump()
    local out = {}
    for _, b in ipairs(M.binds) do
        local payload = b.payload:gsub("\\", "\\\\"):gsub("\t", "\\t"):gsub("\n", "\\n")
        out[#out + 1] = table.concat({ b.release and "1" or "0", b.mouse and "1" or "0", b.keys, b.kind, payload }, "\t")
    end
    return table.concat(out, "\n")
end

return M
