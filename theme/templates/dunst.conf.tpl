{%- set a11y = a11y if a11y is defined else {"motion": "full", "contrast": "normal"} -%}
# dunst colours: theme "{{ theme }}" ({{ meta.name }}), written by `bromigos theme set`.
# Don't edit; a drop-in in ~/.config/dunst/dunstrc.d/ points here. Drop-ins override
# dunstrc key by key, so the layout stays in dunstrc. The formats carry colours, so
# they live here.
[global]
    frame_color = "{{ primary }}"
    highlight = "{{ primary }}"
{%- if a11y.contrast == "high" %}
    # high contrast (bromigos accessibility): a heavier frame, no translucency
    frame_width = 2
    transparency = 0
{%- endif %}
    format = "<span text_transform='uppercase' letter_spacing='1800' size='small' weight='600' foreground='{{ dim }}'>%a</span>\n<b>%s</b>\n%b"

[urgency_low]
    background = "{{ panel }}"
    foreground = "{{ muted }}"
    frame_color = "{{ dim }}"
    highlight = "{{ dim }}"

[urgency_normal]
    background = "{{ panel }}"
    foreground = "{{ soft }}"
    frame_color = "{{ primary }}"

[urgency_critical]
    background = "{{ danger_surface }}"
    foreground = "{{ danger_text }}"
    frame_color = "{{ danger }}"
    highlight = "{{ danger }}"
    format = "<span text_transform='uppercase' letter_spacing='1800' size='small' weight='700' foreground='{{ danger }}'>%a · critical</span>\n<b>%s</b>\n%b"

# capture notifications (category capture.done / capture.live)
[bromigos_capture_done]
    frame_color = "{{ primary }}"

[bromigos_capture_live]
    frame_color = "{{ warn }}"
    highlight = "{{ warn }}"
    format = "<span text_transform='uppercase' letter_spacing='1800' size='small' weight='600' foreground='{{ warn }}'>%a · live</span>\n<b>%s</b>\n%b"
