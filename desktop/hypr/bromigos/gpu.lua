-- GPU selection at login. The Rust hardware probe owns connector/driver policy.
-- Explicit environment and saved hardware settings win; automatic selection runs
-- once per compositor, never moving a running desktop when cables change.
local M = {}
local automatic_checked = false

local function exists(path)
    local ok, _, code = os.rename(path, path)
    return ok == true or code ~= 2
end

local function card_list(value)
    local cards, seen = {}, {}
    for card in value:gmatch("[^:]+") do
        if not card:match("^/dev/dri/card%d+$") or seen[card] then return nil end
        seen[card] = true
        cards[#cards + 1] = card
    end
    if #cards == 0 or table.concat(cards, ":") ~= value then return nil end
    return value
end

function M.apply(B)
    local first = not automatic_checked
    automatic_checked = true
    if B.hw == false then return end

    local inherited = os.getenv("AQ_DRM_DEVICES")
    local selected = inherited ~= nil and inherited ~= ""
    local state = os.getenv("XDG_STATE_HOME")
    if state == nil or state == "" then state = os.getenv("HOME") .. "/.local/state" end
    local ok, hw = pcall(dofile, state .. "/bromigos/hw/hyprland.lua")
    if ok and type(hw) == "table" then
        for _, e in ipairs(hw.env or {}) do
            local valid = type(e[1]) == "string" and type(e[2]) == "string"
            for _, path in ipairs(e.when or {}) do
                if not exists(path) then valid = false end
            end
            if valid and not (e[1] == "AQ_DRM_DEVICES" and selected) then
                hl.env(e[1], e[2])
                if e[1] == "AQ_DRM_DEVICES" and e[2] ~= "" then selected = true end
            end
        end
    end
    if selected or not first then return end

    -- Absolute commands keep login independent of shell startup. A partial package
    -- update, unavailable probe or unclear hardware leaves Hyprland's default intact.
    local opened, pipe = pcall(io.popen,
        "/usr/bin/timeout 2s /usr/bin/bromigos hw display --hyprland 2>/dev/null", "r")
    if not opened or not pipe then return end
    local output = pipe:read("*a") or ""
    local success = pipe:close()
    if not success then return end
    local devices = card_list(output:match("^%s*(.-)%s*$"))
    if devices then hl.env("AQ_DRM_DEVICES", devices) end
end

return M
