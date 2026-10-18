-- bromigOS's Hyprland defaults (package bromigos-desktop, Hyprland >= 0.55, Lua config).
-- Installed as /usr/share/bromigos/default/hypr/hyprland.lua; don't edit it, updates
-- replace it. Your ~/.config/hypr/hyprland.lua runs it and then adds your own:
--
--   bromigos = { mod = "ALT", monitors = { ... } }     -- optional settings, below
--   dofile("/usr/share/bromigos/default/hypr/hyprland.lua")
--   hl.window_rule({ match = { class = "Steam" }, workspace = "4" })   -- yours after
--
-- Settings (all optional), the global `bromigos` table set before this file runs:
--   mod        the main modifier for the window binds ("ALT"); with "SUPER", bromigOS's own
--              Super keys they'd share move to Alt (bromigos/keys.lua, K.finish)
--   monitors   { { output = "<name>", mode = "<w>x<h>@<hz>", position = "0x0", scale = 1 }, ... }
--              pins those outputs (`bromigos setup monitors` writes them); any other output
--              lights up at its preferred mode, placed automatically, scaled by its density
--   workspaces { { first = 1, last = 5, monitor = "<name>" }, ... }: those workspaces open on
--              that monitor, and their keys focus it first (none: 1-10 split left to right
--              across the monitors there are, again on hotplug)
--   apps       { terminal = "kitty", files = "pcmanfm" }
--   config     a table merged over the hl.config() below (e.g. input = { kb_options = "caps:escape" })
--   unbind     { "XF86AudioMicMute", ... }: default binds you make yourself instead
--   polkit     false: don't start bromigOS's polkit agent (hyprpolkitagent)
--   hw         false: ignore this machine's GPU environment (`bromigos hw setup` writes it)
--   gestures   false: no touchpad gestures (three fingers sideways switch workspaces)
--   autostart  { "cmd", ... }: more commands at login, after bromigOS's
--
-- Layout: this file (monitors, autostart, env, look, input, rules, workspaces),
-- bromigos/binds.lua (keybinds), bromigos/live.lua (the live layer's), bromigos/vector.lua
-- (VECTOR's, when it's installed), bromigos/peripherals.lua (the peripheral modules you
-- turned on: `bromigos peripheral`), bromigos/keys.lua (bind helpers). Check a config:
-- Hyprland --verify-config -c ~/.config/hypr/hyprland.lua. API: /usr/share/hypr/stubs/hl.meta.lua.

bromigos = type(bromigos) == "table" and bromigos or {}
local B = bromigos
local share = os.getenv("BROMIGOS_SHARE_DIR")
if share == nil or share == "" then share = "/usr/share/bromigos" end
B.share = B.share or share
B.mod = B.mod or "ALT"
B.apps = B.apps or {}
B.apps.terminal = B.apps.terminal or "kitty"
B.apps.files = B.apps.files or "pcmanfm"
local defaults = B.share .. "/default/hypr"
package.path = defaults .. "/?.lua;" .. package.path

-- Monitors: plug and play. Every output lights up: a catch-all rule (its preferred mode,
-- placed automatically) covers any output, also one plugged in later, and each output
-- not named in bromigos.monitors gets a scale from its pixel density (the EDID's physical
-- size: ~110 px per inch at 1x, so a 27" 1440p desktop is 1x, a 4K laptop 2x).
-- bromigos.monitors pins named outputs (yours, or the block `bromigos setup monitors`
-- writes in your hyprland.lua).
local named = {}
for _, m in ipairs(B.monitors or {}) do
    hl.monitor(m)
    named[m.output] = true
end
hl.monitor({ output = "", mode = "preferred", position = "auto", scale = "auto" })

local STEPS = { 1, 1.25, 1.5, 1.75, 2 }
--- An output's scale from its pixel density; by its height when the EDID gives no size.
function B.auto_scale(m)
    local w, pw = m.width or 0, m.physical_width or 0
    local want
    if pw > 0 and w > 0 then
        want = (w / (pw / 25.4)) / 110
    else
        want = (m.height or 0) >= 2000 and 1.5 or 1
    end
    local best = STEPS[1]
    for _, s in ipairs(STEPS) do
        if math.abs(s - want) < math.abs(best - want) then best = s end
    end
    return best
end

-- Workspaces across several monitors, unless bromigos.workspaces says otherwise: 1-10
-- split left to right (two monitors: 1-5 and 6-10), again whenever one comes, goes or
-- moves; back to the one left when a monitor is unplugged.
local split_done = false
local function split_workspaces()
    if B.workspaces and #B.workspaces > 0 then return end
    local ok, mons = pcall(hl.get_monitors)
    if not ok or type(mons) ~= "table" or #mons == 0 then return end
    if #mons == 1 then
        if split_done then                     -- unplugged: every workspace on the one left
            for k = 1, 10 do hl.workspace_rule({ workspace = tostring(k), monitor = mons[1].name }) end
            split_done = false
        end
        return
    end
    -- left to right; a monitor just added may not be placed yet (x ties): then by id
    table.sort(mons, function(a, b)
        if (a.x or 0) ~= (b.x or 0) then return (a.x or 0) < (b.x or 0) end
        return (a.id or 0) < (b.id or 0)
    end)
    local n, ws = #mons, 1
    for i, m in ipairs(mons) do
        local count = math.floor(10 / n) + ((i <= 10 % n) and 1 or 0)
        for k = ws, ws + count - 1 do
            hl.workspace_rule({ workspace = tostring(k), monitor = m.name })
        end
        ws = ws + count
    end
    split_done = true
end

local function fit_outputs()
    local ok, mons = pcall(hl.get_monitors)
    if not ok or type(mons) ~= "table" then return end
    for _, m in ipairs(mons) do
        if m.name and not named[m.name] then
            local s = B.auto_scale(m)
            if math.abs((m.scale or 1) - s) > 0.01 then
                hl.monitor({ output = m.name, mode = "preferred", position = "auto", scale = s })
            end
        end
    end
    split_workspaces()
end
-- the wallpaper follows the outputs (a second later: the list has settled); the command
-- first, so a failing rule can't stop it
local function wallpaper_outputs()
    hl.exec_cmd("sh -c 'sleep 1; exec bromigos-wallpaper outputs'")
end
hl.on("monitor.added", function()
    wallpaper_outputs()
    pcall(fit_outputs)
end)
hl.on("monitor.removed", function()
    wallpaper_outputs()
    pcall(split_workspaces)
end)
hl.on("monitor.layout_changed", function() pcall(split_workspaces) end)
fit_outputs()

-- Autostart: runs once at login (not on reload). The live layer starts from bromigos/live.lua.
hl.on("hyprland.start", function()
    -- this session's display for systemd/D-Bus, and VECTOR's daemon moved off any old session
    hl.exec_cmd("bromigos session adopt")
    -- XEmbed tray icons in the bar; the bridge needs Wayland click forwarding.
    hl.exec_cmd("env XDG_SESSION_TYPE=wayland xembedsniproxy")
    hl.exec_cmd("waybar")
    hl.exec_cmd("bromigos game --watch")
    -- the still wallpaper under the live layer (the theme's painting, or the den's variant)
    hl.exec_cmd("bromigos wallpaper apply")
    hl.exec_cmd("bromigos-widgets")
    -- the idle policy: ~/.config/bromigos/idle.toml rendered, then hypridle (docs/idle.md)
    hl.exec_cmd("bromigos idle start")
    hl.exec_cmd("/usr/bin/hyprctl setcursor Bromigos-cursor 24")
    hl.exec_cmd("dunst")
    -- floating windows put back where they were (opt-in: ~/.config/bromigos/windows.toml; exits otherwise)
    hl.exec_cmd("bromigos-windows")
    -- the on-screen display (volume, brightness, mute), in the theme's colours
    -- (hooks/theme-set.d/osd starts it again on a theme switch)
    local osd = io.open("/usr/bin/swayosd-server", "r")
    if osd then
        osd:close()
        local st = os.getenv("XDG_STATE_HOME")
        if st == nil or st == "" then st = os.getenv("HOME") .. "/.local/state" end
        hl.exec_cmd("swayosd-server --style " .. st .. "/bromigos/theme/current/swayosd.css")
    end
    -- the polkit agent: answers graphical password prompts (pkexec, mounts, NetworkManager);
    -- off with bromigos.polkit = false when the user runs another agent
    if B.polkit ~= false then
        hl.exec_cmd("/usr/lib/hyprpolkitagent/hyprpolkitagent")
    end
    for _, cmd in ipairs(B.autostart or {}) do
        hl.exec_cmd(cmd)
    end
end)

-- Session environment. Cursor theme: Bromigos-cursor; Qt/KDE apps (Dolphin, file dialogs,
-- OBS) read the theme's colour scheme through KDE's platform theme.
hl.env("XCURSOR_THEME", "Bromigos-cursor")
hl.env("XCURSOR_SIZE", "24")
hl.env("QT_QPA_PLATFORMTHEME", "kde")

-- This machine's GPU environment, written by `bromigos hw setup` into
-- ~/.local/state/bromigos/hw/hyprland.lua (docs/hardware.md): on a hybrid laptop, the GPU
-- the desktop renders on (AQ_DRM_DEVICES, the integrated one first). A variable is set
-- only while every path in its `when` exists, so a GPU swapped since can't break the
-- session. NVIDIA alone needs none.
local function exists(path)
    -- renaming a path to itself changes nothing: no such file is ENOENT (2); anything else
    -- (done, or not allowed in a root-owned folder) means it's there
    local ok, _, code = os.rename(path, path)
    return ok == true or code ~= 2
end
if B.hw ~= false then
    local state = os.getenv("XDG_STATE_HOME")
    if state == nil or state == "" then state = os.getenv("HOME") .. "/.local/state" end
    local ok, hw = pcall(dofile, state .. "/bromigos/hw/hyprland.lua")
    if ok and type(hw) == "table" then
        for _, e in ipairs(hw.env or {}) do
            local all = type(e[1]) == "string" and type(e[2]) == "string"
            for _, p in ipairs(e.when or {}) do
                if not exists(p) then all = false end
            end
            if all then hl.env(e[1], e[2]) end
        end
    end
end

-- Colours: the active bromigOS theme (borders, shadows), rendered by `bromigos theme set`
-- into ~/.local/state/bromigos/theme/current/hyprland.lua, which returns a table. Read
-- with dofile, so `hyprctl reload` (which `theme set` runs) always picks up a new theme.
-- Missing (no theme set yet): Hyprland's default colours.
local theme = {}
do
    local state = os.getenv("XDG_STATE_HOME")
    if state == nil or state == "" then state = os.getenv("HOME") .. "/.local/state" end
    local ok, t = pcall(dofile, state .. "/bromigos/theme/current/hyprland.lua")
    if ok and type(t) == "table" then theme = t end
end

-- `bromigos.config` merged over this table: yours wins, key by key.
local function merge(into, over)
    for k, v in pairs(over or {}) do
        if type(v) == "table" and type(into[k]) == "table" then
            merge(into[k], v)
        else
            into[k] = v
        end
    end
    return into
end

hl.config(merge({
    input = {
        repeat_rate  = 50,
        repeat_delay = 240,
        sensitivity  = 1.0, -- for mouse cursor

        touchpad = {
            disable_while_typing    = true,
            natural_scroll          = true,
            clickfinger_behavior    = true,
            middle_button_emulation = false,
            tap_to_click            = true,    -- one finger: click, two: right, three: middle
        },
    },

    general = {
        layout = "master",
        gaps_in     = 4,
        gaps_out    = 12,
        border_size = theme.border_size or 2,   -- 3 in high contrast (bromigos accessibility)
        col = {
            active_border   = theme.active_border,
            inactive_border = theme.inactive_border,
        },
    },

    decoration = {
        -- square corners, the theme's shadow
        rounding = 0,
        shadow = {
            enabled        = true,
            range          = 16,
            render_power   = 3,
            color          = theme.shadow,
            color_inactive = theme.shadow_inactive,
        },
        blur = {
            enabled = true,
            size    = 3,
            passes  = 1,
        },
    },

    -- off when you asked for a still desktop (bromigos accessibility motion still)
    animations = {
        enabled = theme.motion ~= "still",
    },

    dwindle = {
        force_split = 2,
    },

    master = {
        new_on_top = true,
    },

    misc = {
        disable_hyprland_logo    = true,
        disable_splash_rendering = true,
        mouse_move_enables_dpms  = true,
        -- a crashed lock screen can be replaced by a fresh one (you still type your
        -- password) instead of only being cleared from a tty
        allow_session_lock_restore = true,
    },
}, B.config))

-- Crisp, quick animations. Reduced motion (bromigos accessibility motion reduced, rendered
-- into the theme's table): nothing pops in or slides; windows and workspaces only fade.
local calm = theme.motion == "reduced" or theme.motion == "still"
hl.curve("crisp", { type = "bezier", points = { { 0.2, 0.9 }, { 0.1, 1 } } })
hl.curve("snap", { type = "bezier", points = { { 0.4, 0 }, { 0.2, 1 } } })
hl.animation({ leaf = "windows", enabled = not calm, speed = 3, bezier = "crisp", style = "popin 92%" })
hl.animation({ leaf = "windowsOut", enabled = not calm, speed = 2, bezier = "snap", style = "popin 92%" })
hl.animation({ leaf = "border", enabled = true, speed = 4, bezier = "snap" })
hl.animation({ leaf = "fade", enabled = true, speed = 3, bezier = "snap" })
hl.animation({ leaf = "layers", enabled = true, speed = 2, bezier = "snap", style = "fade" })
hl.animation({ leaf = "workspaces", enabled = true, speed = 3, bezier = "crisp", style = calm and "fade" or "slide" })

-- Layer rules: blur behind the translucent bar, launcher, notifications and desktop
-- panels (ignore_alpha keeps it off their fully transparent pixels), and VECTOR's console
-- and hologram gallery.
for _, namespace in ipairs({ "waybar", "rofi", "notifications", "bromigos-widgets",
                             "bromigos-vector", "bromigos-holo-gallery" }) do
    hl.layer_rule({ match = { namespace = namespace }, blur = true, ignore_alpha = 0.2 })
end

-- Window rules (applied top to bottom). Find a window's class and title: hyprctl clients.
hl.window_rule({ match = { class = "kitty" }, tile = true })
-- KDE's bridge keeps an X11 host window for the embedded icon. Hide only that
-- helper (KDE >= 6.7 names it), leaving each app's menus alone.
hl.window_rule({ match = { class = "^xembedsniproxy$" }, opacity = "0.0 override", no_blur = true })
-- Apps (Chrome especially) ask to open maximized; ignore it so new windows tile.
hl.window_rule({ match = { class = ".*" }, suppress_event = "maximize" })
hl.window_rule({ match = { class = "Rofi" }, float = true })
hl.window_rule({ match = { class = "Rofi" }, move = "25% 40%" })
hl.window_rule({ match = { class = "Rofi" }, size = "50% 20%" })
hl.window_rule({ match = { class = "Rofi" }, opacity = "0.80" })
hl.window_rule({ match = { class = "Rofi" }, center = true })

-- Workspaces: on the monitors you named.
for _, w in ipairs(B.workspaces or {}) do
    for ws = w.first, w.last do
        hl.workspace_rule({ workspace = tostring(ws), monitor = w.monitor })
    end
end

-- Touchpad gestures (only a touchpad makes them): three fingers sideways switch workspaces,
-- one for one. bromigos.gestures = false leaves them out; yours go after the defaults
-- (e.g. hl.gesture({ fingers = 3, direction = "down", mods = "SUPER", action = "close" })).
if B.gestures ~= false then
    hl.gesture({ fingers = 3, direction = "horizontal", action = "workspace" })
end

local K = require("bromigos.keys")
K.defaults = true
-- peripheral modules first (bromigos peripheral): their keys' exclusions apply to the binds after
require("bromigos.peripherals")
require("bromigos.binds")
require("bromigos.live")
require("bromigos.dictation")
require("bromigos.vector")
K.exec("SUPER + CTRL + G", "bromigos game toggle")
hl.define_submap("bromigos-game", function()
    hl.bind("CTRL + SHIFT + F12", function()
        -- Reset first: the escape key works even when the helper cannot answer.
        hl.dispatch(hl.dsp.submap("reset"))
        hl.exec_cmd("bromigos game off")
    end, { description = "Leave game mode", locked = true })
end)
K.finish()   -- binds them all: a desktop key a window key would share moves (keys.lua)
