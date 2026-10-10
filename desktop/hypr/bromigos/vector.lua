-- VECTOR's binds, when VECTOR is installed (its launcher, bromigos-holo, is found).
-- Required by the defaults' hyprland.lua.

local K = require("bromigos.keys")

local home = os.getenv("HOME") or ""
local holo
for _, p in ipairs({ "/usr/bin/bromigos-holo", "/usr/lib/bromigos/vector/bin/bromigos-holo" }) do
    local f = io.open(p, "r")
    if f then
        f:close()
        holo = p
        break
    end
end
if not holo then
    local f = io.open(home .. "/.config/bromigos/holo/bin/bromigos-holo", "r")
    if f then
        f:close()
        holo = "~/.config/bromigos/holo/bin/bromigos-holo"
    end
end
if not holo then
    return
end

-- VECTOR, on the line (typed; Esc hands the keyboard back) / the hologram gallery.
K.exec("SUPER + E", holo .. " vector")
-- Conversation mode: hands-free, listens until you stop talking, replies, listens again.
K.exec("SUPER + SHIFT + E", holo .. " conversation")
K.exec("SUPER + O", holo .. " gallery")
-- Push-to-talk: the mic is open only while SUPER+V is held / mute everything (VECTOR's
-- voice with the theme's sounds, as SUPER+SHIFT+M; the bar pip's middle-click mutes him alone).
K.exec("SUPER + V", holo .. " ptt on")
K.exec("SUPER + V", holo .. " ptt off", { release = true })
K.exec("SUPER + SHIFT + V", "bromigos mute")
K.exec("SUPER + ALT + V", holo .. " chat")
-- Follow mode: VECTOR reads Claude Code's replies aloud as they finish, until pressed again.
K.exec("SUPER + ALT + C", holo .. " claude follow toggle")
-- The emergency switch: VECTOR off at once (his commands, his answer, his speech); while
-- he's off, the same keys ask YES before switching him back on. Works with his daemon hung.
K.exec("SUPER + CTRL + ESCAPE", holo .. " switch toggle --from=key")
