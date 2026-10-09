/* gtklock colours: theme "{{ theme }}" ({{ meta.name }}), written by `bromigos theme set`.
   Don't edit; the lock screen's style.css imports this file and uses the names. */
{% for name, value in palette -%}
@define-color {{ name }} {{ value }};
{% endfor -%}
