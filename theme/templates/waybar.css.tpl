{%- set a11y = a11y if a11y is defined else {"motion": "full", "contrast": "normal"} -%}
/* waybar colours: theme "{{ theme }}" ({{ meta.name }}), written by `bromigos theme set`.
   Don't edit; style.css imports this file and uses the names. */
{% for name, value in palette -%}
@define-color {{ name }} {{ value }};
{% endfor -%}

/* The bar's icons, drawn in this theme's colours (icons/ beside this file): waybar's
   style.css sets their size and place, this sets the images. A url here is relative to
   this file, so the bar's style can live anywhere (bromigOS ships it in /usr/share). */
#custom-launcher              { background-image: url("icons/emblem.svg"); }
#cpu                          { background-image: url("icons/cpu.svg"); }
#cpu.warning                  { background-image: url("icons/cpu-amber.svg"); }
#cpu.critical                 { background-image: url("icons/cpu-danger.svg"); }
#memory                       { background-image: url("icons/ram.svg"); }
#memory.warning               { background-image: url("icons/ram-amber.svg"); }
#memory.critical              { background-image: url("icons/ram-danger.svg"); }
#custom-gpu                   { background-image: url("icons/gpu.svg"); }
#custom-gpu.warning           { background-image: url("icons/gpu-amber.svg"); }
#custom-gpu.critical          { background-image: url("icons/gpu-danger.svg"); }
#temperature                  { background-image: url("icons/temp.svg"); }
#temperature.warning          { background-image: url("icons/temp-amber.svg"); }
#temperature.critical         { background-image: url("icons/temp-danger.svg"); }
#custom-storage               { background-image: url("icons/disk.svg"); }
#custom-storage.warning       { background-image: url("icons/disk-amber.svg"); }
#custom-storage.critical      { background-image: url("icons/disk-danger.svg"); }
#network                      { background-image: url("icons/net.svg"); }
#network.disconnected,
#network.linked               { background-image: url("icons/net-amber.svg"); }
#power-profiles-daemon        { background-image: url("icons/power.svg"); }
#power-profiles-daemon.performance { background-image: url("icons/power-amber.svg"); }
#power-profiles-daemon.power-saver { background-image: url("icons/power-dim.svg"); }
#battery                      { background-image: url("icons/bat.svg"); }
#battery.full,
#battery.plugged              { background-image: url("icons/bat-dim.svg"); }
#battery.warning              { background-image: url("icons/bat-amber.svg"); }
#battery.critical             { background-image: url("icons/bat-danger.svg"); }
#battery.charging             { background-image: url("icons/bat.svg"); }
#pulseaudio                   { background-image: url("icons/vol.svg"); }
#pulseaudio.muted             { background-image: url("icons/vol-muted-amber.svg"); }
#mpris                        { background-image: url("icons/tape.svg"); }
#mpris.paused                 { background-image: url("icons/tape-dim.svg"); }
#clock                        { background-image: url("icons/clock.svg"); }
#custom-vector                { background-image: url("icons/vector.svg"); }
#custom-vector.minimized      { background-image: url("icons/vector-dim.svg"); }
#custom-vector.thinking,
#custom-vector.listening      { background-image: url("icons/vector-amber.svg"); }
#custom-vector.speaking       { background-image: url("icons/vector.svg"); }
#custom-vector.error          { background-image: url("icons/vector-danger.svg"); }
#custom-vector.conversation   { background-image: url("icons/vector-danger.svg"); }
#custom-vector.mood-concerned { background-image: url("icons/vector-amber.svg"); }
#custom-vector.mood-alarmed   { background-image: url("icons/vector-danger.svg"); }
#custom-idle                  { background-image: url("icons/eye-dim.svg"); }
#custom-idle.saver,
#custom-idle.nothing          { background-image: url("icons/eye.svg"); }
#custom-idle.awake            { background-image: url("icons/cup-amber.svg"); }
#custom-idle.stopped          { background-image: url("icons/eye-danger.svg"); }
#custom-settings              { background-image: url("icons/gear-dim.svg"); }
#custom-settings:hover        { background-image: url("icons/gear.svg"); }
/* Bluetooth: the rune dim while off, lit while on; while a device is connected, its
   battery as a sliver of five cells under the rune, amber at 15% or under */
#custom-bluetooth             { background-image: url("icons/bt-dim.svg"); }
#custom-bluetooth.on,
#custom-bluetooth.connected   { background-image: url("icons/bt.svg"); }
#custom-bluetooth.problem     { background-image: url("icons/bt-amber.svg"); }
#custom-bluetooth.connected.c0 { background-image: url("icons/bt.svg"), url("icons/btcell-0.svg"); }
#custom-bluetooth.connected.c1 { background-image: url("icons/bt.svg"), url("icons/btcell-1.svg"); }
#custom-bluetooth.connected.c2 { background-image: url("icons/bt.svg"), url("icons/btcell-2.svg"); }
#custom-bluetooth.connected.c3 { background-image: url("icons/bt.svg"), url("icons/btcell-3.svg"); }
#custom-bluetooth.connected.c4 { background-image: url("icons/bt.svg"), url("icons/btcell-4.svg"); }
#custom-bluetooth.connected.c5 { background-image: url("icons/bt.svg"), url("icons/btcell-5.svg"); }
#custom-bluetooth.connected.low.c0 { background-image: url("icons/bt-amber.svg"), url("icons/btcell-0-amber.svg"); }
#custom-bluetooth.connected.low.c1 { background-image: url("icons/bt-amber.svg"), url("icons/btcell-1-amber.svg"); }
#custom-bluetooth.connected.low.c2 { background-image: url("icons/bt-amber.svg"), url("icons/btcell-2-amber.svg"); }
#custom-bluetooth.connected.low.c3 { background-image: url("icons/bt-amber.svg"), url("icons/btcell-3-amber.svg"); }
#custom-bluetooth.connected.low.c4 { background-image: url("icons/bt-amber.svg"), url("icons/btcell-4-amber.svg"); }
#custom-bluetooth.connected.low.c5 { background-image: url("icons/bt-amber.svg"), url("icons/btcell-5-amber.svg"); }
{%- if a11y.contrast == "high" %}

/* High contrast (bromigos accessibility): the bar opaque, its rules solid, no glow behind
   text. These come before bromigOS's style.css, so each selector carries a :not() that
   gives it the weight to win over the default's same rule. */
window#waybar:not(.bromigos-a11y) {
  background-color: @panel;
  border-bottom: 2px solid @dim;
}
#cpu:not(.bromigos-a11y), #memory:not(.bromigos-a11y), #custom-gpu:not(.bromigos-a11y),
#temperature:not(.bromigos-a11y), #custom-storage:not(.bromigos-a11y),
#network:not(.bromigos-a11y), #pulseaudio:not(.bromigos-a11y), #tray:not(.bromigos-a11y),
#clock:not(.bromigos-a11y), #mpris:not(.bromigos-a11y), #window:not(.bromigos-a11y),
#custom-launcher:not(.bromigos-a11y), #custom-idle:not(.bromigos-a11y),
#custom-settings:not(.bromigos-a11y), #custom-bluetooth:not(.bromigos-a11y) {
  border-color: @dim;
  text-shadow: none;
}
#workspaces button:not(.bromigos-a11y) { text-shadow: none; }
#workspaces button.empty:not(.bromigos-a11y) { color: @muted; }
#workspaces button.active:not(.bromigos-a11y) { background-color: @selection; }
#workspaces button:hover:not(.bromigos-a11y),
#custom-launcher:hover:not(.bromigos-a11y) { background-color: @selection; }
#custom-vector:not(.bromigos-a11y) { text-shadow: none; }
tooltip:not(.bromigos-a11y) { border: 2px solid @primary; }
{%- endif %}
