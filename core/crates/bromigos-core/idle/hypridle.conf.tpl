# bromigOS's idle policy for hypridle, rendered by `bromigos idle` from
# ~/.config/bromigos/idle.toml over the defaults in /usr/share/bromigos/default/idle.toml
# (template: /usr/share/bromigos/idle/hypridle.conf.tpl). Don't edit: every change is
# rendered again. Your ~/.config/hypr/hypridle.conf sources this file, then adds yours.
#
# {{ summary }}

general {
    lock_cmd = bromigos lock-run   # relaunches the locker if it crashes; you still type your password
{%- if lock_before_sleep %}
    before_sleep_cmd = loginctl lock-session
{%- endif %}
    after_sleep_cmd = {{ dispatch }} 'hl.dsp.dpms({ action = "on" })' dpms on
}
{%- if screensaver.enabled %}

# the screensaver: the live scene full screen; any input ends it
listener {
    timeout = {{ screensaver.seconds }}
    on-timeout = bromigos-live ctl screensaver open
    on-resume = bromigos-live screensaver-off
}
{%- endif %}
{%- if lock.enabled %}

# the lock
listener {
    timeout = {{ lock.seconds }}
    on-timeout = loginctl lock-session
}
{%- endif %}
{%- if displays.enabled %}

# the displays off (Lua dispatchers for hyprland.lua; the old `dpms` form for hyprland.conf)
listener {
    timeout = {{ displays.seconds }}
    on-timeout = {{ dispatch }} 'hl.dsp.dpms({ action = "off" })' dpms off
    on-resume = {{ dispatch }} 'hl.dsp.dpms({ action = "on" })' dpms on
}
{%- endif %}
{%- if suspend.enabled %}

# suspend
listener {
    timeout = {{ suspend.seconds }}
    on-timeout = systemctl suspend
}
{%- endif %}
{%- if activity.enabled %}

# the worlds' keeper and creatures doze without input and wake on the next
listener {
    timeout = {{ activity.seconds }}
    on-timeout = bromigos-live ctl activity idle
    on-resume = bromigos-live ctl activity active
}
{%- endif %}
