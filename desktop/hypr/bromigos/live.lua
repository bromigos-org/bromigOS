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
-- off; and the standalone Den TV app.
K.exec("SUPER + ALT + P", live .. " tv open")
K.exec("SUPER + ALT + period", live .. " tv next")
K.exec("SUPER + ALT + comma", live .. " tv prev")
K.exec("SUPER + ALT + M", live .. " tv sound toggle")
K.exec("SUPER + ALT + G", live .. " tv guide")

-- Physical number-pad codes work with NumLock on or off (KP_1 / KP_End share a code).
-- The daemon selects the TV, enters the submap and resets it after 15 seconds idle.
-- Remote actions retain their submap when rebound in Settings (keys.lua).
K.exec("SUPER + code:90", live .. " tv select none")
K.exec("SUPER + code:87", live .. " tv select big")
K.exec("SUPER + code:88", live .. " tv select scope")
K.exec("SUPER + code:89", live .. " tv select small")
K.exec("code:86", live .. " tv remote volume-up", { repeating = true })
K.exec("code:82", live .. " tv remote volume-down", { repeating = true })
K.exec("code:80", live .. " tv remote channel-up")
K.exec("code:88", live .. " tv remote channel-down")
K.exec("code:84", live .. " tv remote mute")
K.exec("code:85", live .. " tv remote skip")
K.exec("code:83", live .. " tv remote previous")
K.exec("code:104", live .. " tv remote open")
K.exec("code:63", live .. " tv remote sound")
K.exec("code:106", live .. " tv remote guide")
K.exec("code:91", live .. " tv remote digits")
K.exec("code:90", live .. " tv remote leave")
K.exec("Escape", live .. " tv remote cancel")
K.exec("code:87", live .. " tv remote digit-1")
K.exec("code:89", live .. " tv remote digit-3")
K.exec("code:79", live .. " tv remote digit-7")
K.exec("code:81", live .. " tv remote digit-9")
