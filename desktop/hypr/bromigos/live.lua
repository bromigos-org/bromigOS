-- The live layer (package bromigos-live): its start at login and its binds. Required by
-- the defaults' hyprland.lua. Decks from personal plugins (~/.config/bromigos/plugins/live)
-- get their binds in the user's own hyprland.lua.

local K = require("bromigos.keys")

local live = "bromigos-live"

hl.on("hyprland.start", function()
    hl.exec_cmd(live .. " start --login")
end)
hl.layer_rule({ match = { namespace = "^(bromigos-live.*)$" }, no_anim = true })
-- Holo deck: arc rings, cluster constellation, machine hologram (Esc closes).
K.exec("SUPER + H", live .. " holodeck")
-- Lab deck: the homelab console as a hologram, the rack lit by live readings
-- (bromigos-homelab; with no lab connected it says so).
K.exec("SUPER + SHIFT + H", live .. " lab")
-- Drift map: the lore catalog as a star chart.
K.exec("SUPER + M", live .. " driftmap")
-- Timeline: the local history (minute samples, 72 h) as a 3D ribbon to scrub.
K.exec("SUPER + T", live .. " timeline")
-- Swarm: repos and agent starships (Tab cycles through every deck).
K.exec("SUPER + SHIFT + S", live .. " swarm")
-- Radial quick-launch (rofi stays the full launcher).
K.exec("SUPER + A", live .. " radial")
-- Live background on/off.
K.exec("SUPER + SHIFT + B", live .. " toggle")
-- Mute everything: the theme's sounds (cues, codec calls) and VECTOR's voice together.
K.exec("SUPER + SHIFT + M", "bromigos mute")
-- Codec calls without voice (quiet mode toggle).
K.exec("SUPER + SHIFT + C", live .. " codec-quiet")
-- Scanner: pin the hardware schematic (toggle) / hold to scan (release hides it).
K.exec("SUPER + X", live .. " scan-pin")
K.exec("SUPER + Z", live .. " scan-hold on")
K.exec("SUPER + Z", live .. " scan-hold off", { release = true })
-- The den TV (live/README.md, "The den TV"): on the screen under the pointer (else the one
-- with the sound): full screen with sound, the next and previous channel, its sound on or
-- off; and the channel guide (Settings › Den TV).
K.exec("SUPER + ALT + P", live .. " tv open")
K.exec("SUPER + ALT + period", live .. " tv next")
K.exec("SUPER + ALT + comma", live .. " tv prev")
K.exec("SUPER + ALT + M", live .. " tv sound toggle")
K.exec("SUPER + ALT + G", live .. " tv guide")
