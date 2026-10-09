{%- set a11y = a11y if a11y is defined else {"motion": "full", "contrast": "normal"} -%}
/* rofi colours: theme "{{ theme }}" ({{ meta.name }}), written by `bromigos theme set`.
   Don't edit; the launcher's theme @imports this file and uses the names. */
* {
{%- for name, value in palette %}
    {{ name | kebab }}: {{ value }};
{%- endfor %}

{%- if a11y.contrast == "high" %}

    /* high contrast (bromigos accessibility): the launcher's layers opaque, the matched
       letters underlined as well as bold */
    selected-tab-background: {{ selection }};
    input-background: {{ void }};
    input-border: {{ dim }};
    selected-background: {{ selection }};
    selected-urgent-background: {{ warn_surface }};
    match-highlight: bold underline {{ primary }};
{%- else %}

    /* the launcher's translucent layers, and the matched letters */
    selected-tab-background: {{ primary }}14;
    input-background: {{ void }}cc;
    input-border: {{ dim }}99;
    selected-background: {{ selection }}cc;
    selected-urgent-background: {{ warn_surface }}cc;
    match-highlight: bold {{ primary }};
{%- endif %}
}
