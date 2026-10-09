-- Your Hyprland: bromigOS's defaults, then yours. bromigOS made this file once; it's yours
-- now (updates never touch it). The defaults and every setting are described in
-- /usr/share/bromigos/default/hypr/hyprland.lua. Check it: Hyprland --verify-config -c <this file>.

bromigos = {
    -- mod = "ALT",
    -- monitors = { { output = "DP-1", mode = "2560x1440@60", position = "0x0", scale = 1 } },
    -- workspaces = { { first = 1, last = 10, monitor = "DP-1" } },
    -- apps = { terminal = "kitty", files = "pcmanfm" },
    -- config = { input = { kb_layout = "us", kb_options = "caps:escape" } },
    -- unbind = { },
    -- autostart = { },
}
dofile("/usr/share/bromigos/default/hypr/hyprland.lua")

-- Yours below. Binds with the same helpers as bromigOS's (SHORTCUTS lists them):
local K = require("bromigos.keys")
-- K.exec("ALT + W", "firefox")
-- hl.window_rule({ match = { class = "Steam" }, workspace = "4" })
