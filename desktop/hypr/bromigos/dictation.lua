-- Hold the Menu key to dictate into the focused app. The overlay never takes focus.
-- A physical code keeps this working when the Menu key is also a Compose key.
local K = require("bromigos.keys")
K.exec("code:135", "bromigos dictate on")
K.exec("code:135", "bromigos dictate off", { release = true })
hl.layer_rule({ match = { namespace = "bromigos-dictation" }, no_anim = true })
