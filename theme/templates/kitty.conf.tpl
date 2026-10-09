{%- set a11y = a11y if a11y is defined else {"motion": "full", "contrast": "normal"} -%}
# kitty colours: theme "{{ theme }}" ({{ meta.name }}), written by `bromigos theme set`.
# Don't edit; kitty.conf includes this file.
foreground            {{ terminal.foreground }}
background            {{ terminal.background }}
selection_foreground  {{ background }}
selection_background  {{ primary }}
cursor                {{ primary }}
cursor_text_color     {{ background }}
url_color             {{ cyan }}
active_border_color   {{ primary }}
inactive_border_color {{ selection }}
bell_border_color     {{ warn }}
visual_bell_color     {{ warn }}
mark1_background      {{ primary }}
mark2_background      {{ warn }}
mark3_background      {{ danger }}

{% for i in range(16) -%}
color{{ i }} {{ terminal["color" ~ i] }}
{% endfor %}
active_tab_foreground   {{ background }}
active_tab_background   {{ primary }}
inactive_tab_foreground {{ muted }}
inactive_tab_background {{ panel }}
tab_bar_background      {{ background }}
{%- if a11y.contrast == "high" %}

# high contrast (bromigos accessibility): an opaque background, so the text's contrast
# is what was measured (your kitty.conf can still set it after including this file)
background_opacity 1.0
{%- endif %}
