/* The start page's colours: theme "{{ theme }}" ({{ meta.name }}), written by
   `bromigos theme set`. index.html links it after its own style.css. */
:root {
  --void: {{ void }};
  --panel: {{ panel }};
  --guard: {{ selection }};
  --phosphor: {{ primary }};
  --soft: {{ soft }};
  --dim: {{ dim }};
  --amber: {{ warn }};
  --danger: {{ danger }};
  --static: {{ muted }};
  --text: {{ text }};
  --line: rgba({{ dim|rgb }}, 0.45);
  --rule: rgba({{ dim|rgb }}, 0.18);
  --glow: rgba({{ primary|rgb }}, 0.25);
  --tile-hover: {% if theme == "wick" %}#031a03{% else %}{{ selection }}{% endif %};
}
