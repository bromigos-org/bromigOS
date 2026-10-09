-- Peripheral modules (docs/peripherals.md): a Razer keyboard's macro keys and keymap, or
-- any module you turned on with `bromigos peripheral enable` (required by the defaults'
-- hyprland.lua, before the other binds). It applies what `bromigos peripheral` generated
-- into ~/.local/state/bromigos/peripherals/hypr.lua from ~/.config/bromigos/peripherals.toml
-- (yours: change a key there, then `bromigos peripheral refresh`). No module on: nothing.
--
-- Each module's keyboards are tagged (Hyprland device names, every interface), get the
-- module's keymap options after yours (fkeys:basic_13-24 keeps F13-F24 plain), and its
-- keys are bound by keycode on those keyboards only: in Hyprland 0.56 a code:N bind also
-- fires for keys without a keysym on any keyboard, so the device list keeps another
-- keyboard's odd keys from setting them off. Keys a module marks exclusive (a side
-- button the default layout reads as XF86AudioMicMute) have their other binds ignore it.
-- The dial and the lighting are the daemon's (bromigos-peripherals.service), not Hyprland's.

local K = require("bromigos.keys")

local state = os.getenv("XDG_STATE_HOME")
if state == nil or state == "" then state = (os.getenv("HOME") or "") .. "/.local/state" end
local ok, mods = pcall(dofile, state .. "/bromigos/peripherals/hypr.lua")
if not ok or type(mods) ~= "table" then
    return {}
end

-- The keymap options a device gets replace the global ones for it, so they are yours
-- (bromigos.config.input.kb_options, else the config's) followed by the module's.
local function your_options()
    local B = type(bromigos) == "table" and bromigos or {}
    local o = B.config and B.config.input and B.config.input.kb_options
    if type(o) ~= "string" then
        local got_ok, v = pcall(hl.get_config, "input.kb_options")
        o = (got_ok and type(v) == "string") and v or ""
    end
    return o
end

local function join(a, list)
    local out = {}
    for opt in (a or ""):gmatch("[^,%s]+") do
        out[#out + 1] = opt
    end
    for _, opt in ipairs(list or {}) do
        local have = false
        for _, x in ipairs(out) do
            if x == opt then have = true end
        end
        if not have then out[#out + 1] = opt end
    end
    return table.concat(out, ",")
end

local mine = your_options()
for _, m in ipairs(mods) do
    if type(m) == "table" and type(m.tag) == "string" then
        local spec = { tags = m.tag }
        if m.kb_options and #m.kb_options > 0 then
            spec.kb_options = join(mine, m.kb_options)
        end
        for _, name in ipairs(m.devices or {}) do
            local d = {}
            for k, v in pairs(spec) do d[k] = v end
            d.name = name
            hl.device(d)
        end
        for _, keys in ipairs(m.exclusive or {}) do
            K.exclude(keys, m.tag)
        end
        local only_these = { list = { m.tag } }
        for _, b in ipairs(m.binds or {}) do
            K.exec(b.keys, b.cmd, { release = b.release == true, device = only_these })
        end
    end
end
return mods
