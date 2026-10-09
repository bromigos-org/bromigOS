-- bromigOS's keybinds (required by the defaults' hyprland.lua). The live layer's are in
-- live.lua, VECTOR's in vector.lua. Yours go in your ~/.config/hypr/hyprland.lua, after
-- the defaults, with the same helpers:
--   local K = require("bromigos.keys")
--   K.exec("SUPER + Q", "some-tool")                                  -- run a command
--   K.dsp("ALT + P", "hl.dsp.window.pin()")                           -- a dispatcher
--   K.exec("SUPER + V", "... ptt off", { release = true })            -- on key-up
-- Keys are "MODS + KEY" ("SUPER + SHIFT + K"), a keysym, or code:N (evdev code + 8).
-- To bind one of these keys to something else, list it in bromigos.unbind first.
-- SHORTCUTS names exec binds from the EXEC table in bromigOS's widgets/keybinds.py.

local K = require("bromigos.keys")
local B = bromigos
local mainMod = B.mod
-- The keys on bromigos.mod pass this. With mod = "SUPER", one of the desktop's own Super
-- keys with the same letter moves to Alt instead (keys.lua, K.finish).
local MOD = { mod = true }

K.dsp(mainMod .. " + mouse:272", "hl.dsp.window.drag()", { mouse = true, mod = true })
K.dsp(mainMod .. " + mouse:273", "hl.dsp.window.resize()", { mouse = true, mod = true })

K.exec(mainMod .. " + b", "pkill -SIGUSR1 waybar", MOD)
K.dsp(mainMod .. " + SHIFT + C", "hl.dsp.window.close()", MOD)
K.dsp(mainMod .. " + F", 'hl.dsp.window.fullscreen({ mode = "maximized" })', MOD)
K.dsp(mainMod .. " + SHIFT + F", 'hl.dsp.window.fullscreen({ mode = "fullscreen" })', MOD)
K.exec(mainMod .. " + SHIFT + RETURN", B.apps.terminal, MOD)
K.dsp(mainMod .. " + C", "hl.dsp.window.close()", MOD)
K.dsp(mainMod .. " + SHIFT + Q", "hl.dsp.exit()", MOD)
K.exec(mainMod .. " + E", B.apps.files, MOD)
K.dsp(mainMod .. " + SHIFT + V", "hl.dsp.window.float()", MOD)
K.exec(mainMod .. " + p", "rofi -show drun", MOD)
-- The desktop menu (launch, install, setup, style, update, toggles; typing searches everything),
-- the theme switcher (previews) and the next wallpaper.
K.exec("SUPER + SPACE", "bromigos-menu")
K.exec("SUPER + CTRL + SHIFT + SPACE", "bromigos-theme-switcher")
K.exec("SUPER + CTRL + SPACE", "bromigos-wallpaper next")
-- Settings: idle and lock, the theme, shortcuts, … (bromigos settings).
K.exec("SUPER + comma", "bromigos settings")
K.exec(mainMod .. " + ESCAPE", "systemctl suspend", MOD)   -- logind lets the active session suspend
-- Screenshots go through bromigos-shot (save, clipboard, cue, notification; click it to
-- annotate in swappy); recording toggles (press again or click the notification to stop).
K.exec(mainMod .. " + Y", "bromigos-shot region", MOD)
K.exec(mainMod .. " + SHIFT + Y", "bromigos-shot screen", MOD)
-- Volume, mic, brightness and media go through the on-screen display (swayosd, which also
-- does the change); pactl/brightnessctl/playerctl directly where it isn't installed.
local osd = io.open("/usr/bin/swayosd-client", "r")
if osd then
    osd:close()
    K.exec("XF86AudioMute", "swayosd-client --output-volume mute-toggle")
    K.exec("XF86AudioLowerVolume", "swayosd-client --output-volume lower")
    K.exec("XF86AudioRaiseVolume", "swayosd-client --output-volume raise")
    K.exec("XF86AudioMicMute", "swayosd-client --input-volume mute-toggle")
    K.exec("XF86MonBrightnessUp", "swayosd-client --brightness raise")
    K.exec("XF86MonBrightnessDown", "swayosd-client --brightness lower")
    K.exec("XF86AudioPlay", "swayosd-client --playerctl play-pause")
    K.exec("XF86AudioPrev", "swayosd-client --playerctl prev")
    K.exec("XF86AudioNext", "swayosd-client --playerctl next")
else
    K.exec("XF86AudioMute", "pactl set-sink-mute @DEFAULT_SINK@ toggle")
    K.exec("XF86AudioLowerVolume", "pactl set-sink-volume @DEFAULT_SINK@ -5%")
    K.exec("XF86AudioRaiseVolume", "pactl set-sink-volume @DEFAULT_SINK@ +5%")
    K.exec("XF86AudioMicMute", "pactl set-source-mute @DEFAULT_SOURCE@ toggle")
    K.exec("XF86MonBrightnessUp", "brightnessctl -q set +5%")   -- increase screen brightness
    K.exec("XF86MonBrightnessDown", "brightnessctl -q set 5%-") -- decrease screen brightness
    K.exec("XF86AudioPlay", "playerctl play-pause")             -- Toggle Media
    K.exec("XF86AudioPrev", "playerctl previous")               -- previous track
    K.exec("XF86AudioNext", "playerctl next")                   -- next track
end
K.exec(mainMod .. " + SHIFT + R", "bromigos-rec region", MOD)

-- Power menu (lock / suspend / logout / reboot / shutdown).
K.exec(mainMod .. " + SHIFT + E", "/usr/lib/bromigos/desktop/rofi/power-menu", MOD)
-- Lock now.
K.exec("SUPER + L", "loginctl lock-session")
-- FIELD NOTES: focus the pad for typing (Esc hands focus back) / quick note from anywhere.
K.exec(mainMod .. " + N", "bromigos-widgets notes", MOD)
K.exec(mainMod .. " + SHIFT + N", "/usr/lib/bromigos/desktop/rofi/quick-note", MOD)
-- Desktop panels: toggle all / one at a time.
K.exec("SUPER + W", "bromigos-widgets toggle all")
K.exec("SUPER + S", "bromigos-widgets toggle system")
K.exec("SUPER + N", "bromigos-widgets toggle network")
K.exec("SUPER + D", "bromigos-widgets toggle storage")
K.exec("SUPER + B", "bromigos-widgets toggle workbench")
K.exec("SUPER + F", "bromigos-widgets toggle notes")
-- Shortcuts: the keybind panel / a searchable cheat sheet that runs the chosen bind.
K.exec("SUPER + K", "bromigos-widgets toggle shortcuts")
K.exec("SUPER + SHIFT + K", "python3 /usr/lib/bromigos/widgets/keybinds.py rofi")
-- Launcher: window switcher.
K.exec(mainMod .. " + TAB", "rofi -show window", MOD)

K.dsp(mainMod .. " + RETURN", 'hl.dsp.layout("swapwithmaster")', MOD)
K.dsp(mainMod .. " + j", 'hl.dsp.layout("cyclenext")', MOD)
K.dsp(mainMod .. " + k", 'hl.dsp.layout("cycleprev")', MOD)

K.dsp(mainMod .. " + h", 'hl.dsp.focus({ direction = "left" })', MOD)
K.dsp(mainMod .. " + l", 'hl.dsp.focus({ direction = "right" })', MOD)

K.dsp(mainMod .. " + left", "hl.dsp.window.resize({ x = -40, y = 0, relative = true })", MOD)
K.dsp(mainMod .. " + right", "hl.dsp.window.resize({ x = 40, y = 0, relative = true })", MOD)

K.dsp(mainMod .. " + SHIFT + h", 'hl.dsp.window.move({ direction = "left" })', MOD)
K.dsp(mainMod .. " + SHIFT + l", 'hl.dsp.window.move({ direction = "right" })', MOD)
K.dsp(mainMod .. " + SHIFT + k", 'hl.dsp.window.move({ direction = "up" })', MOD)
K.dsp(mainMod .. " + SHIFT + j", 'hl.dsp.window.move({ direction = "down" })', MOD)

-- The scratchpad: the default special workspace ("special:special").
K.dsp(mainMod .. " + SHIFT + S", 'hl.dsp.window.move({ workspace = "special" })', MOD)
K.dsp(mainMod .. " + s", "hl.dsp.workspace.toggle_special()", MOD)

-- Workspaces 1-10 on the number keys. A workspace given a monitor (bromigos.workspaces)
-- focuses that monitor first (two binds on one key run in order).
local monitor_of = {}
for _, w in ipairs(B.workspaces or {}) do
    for ws = w.first, w.last do
        monitor_of[ws] = w.monitor
    end
end
for ws = 1, 10 do
    local key = tostring(ws % 10)
    if monitor_of[ws] then
        K.dsp(mainMod .. " + " .. key, ('hl.dsp.focus({ monitor = "%s" })'):format(monitor_of[ws]), MOD)
    end
    K.dsp(mainMod .. " + " .. key, ("hl.dsp.focus({ workspace = %d })"):format(ws), MOD)
end

-- Send the active window to a workspace without following it.
for ws = 1, 10 do
    K.dsp(mainMod .. " + SHIFT + " .. tostring(ws % 10),
        ("hl.dsp.window.move({ workspace = %d, follow = false })"):format(ws), MOD)
end

-- The shortcut picker's capture window (`bromigos keys`, SETUP › Shortcuts…): while it
-- listens, Hyprland is in this submap, where nothing else is bound, so every key reaches
-- the window. Esc always leaves it (and still reaches the window, which cancels); the
-- window leaves it when it closes, a watchdog if the window dies, and a timer Hyprland
-- runs itself after a minute. Not made through K: it isn't one of the desktop's keys.
hl.define_submap("bromigos-capture", function()
    hl.bind("ESCAPE", function() hl.dispatch(hl.dsp.submap("reset")) end,
        { non_consuming = true, description = "Leave the shortcut capture" })
end)
