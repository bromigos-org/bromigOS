{%- set a11y = a11y if a11y is defined else {"motion": "full", "contrast": "normal"} -%}
-- Hyprland colours: theme "{{ theme }}" ({{ meta.name }}), written by `bromigos theme set`.
-- Don't edit; hyprland.lua loads this file with dofile() and uses the fields.
return {
{%- if a11y.contrast == "high" %}
    -- high contrast (bromigos accessibility): solid borders, a little wider
    active_border   = "rgb({{ primary | strip }})",
    inactive_border = "rgb({{ selection | strip }})",
    border_size     = 3,
{%- else %}
    active_border   = { colors = { "rgb({{ primary | strip }})", "rgb({{ dim | strip }})" }, angle = 45 },
    inactive_border = "rgba({{ selection | strip }}ee)",
{%- endif %}
    shadow          = "rgba({{ primary | strip }}30)",
    shadow_inactive = "rgba({{ void | strip }}cc)",

    -- the user's accessibility settings (bromigos accessibility): "full", "reduced" or
    -- "still" (the defaults' window animations follow it), "normal" or "high"
    motion   = "{{ a11y.motion }}",
    contrast = "{{ a11y.contrast }}",

    -- every colour of the theme, as Hyprland colour values
    colors = {
{%- for name, value in palette %}
        {{ name }} = "rgb({{ value | strip }})",
{%- endfor %}
    },
}
