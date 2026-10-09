// {{ meta.name }}: the colours in waybar's Pango markup (the formats can't use CSS).
// Rendered by `bromigos theme set` from theme/templates/waybar-markup.jsonc.tpl;
// waybar's config pulls it in with "include", and the keys merge into its modules.
{
  "mpris": {
    "format": "{artist} · {title}  <span color='{{ muted }}'>{position}/{length}</span>",
    "format-paused": "<span color='{{ muted }}'>‖</span> {artist} · {title}"
  },
  "network": {
    "format-wifi": "<span color='{{ muted }}'>⇣</span>{bandwidthDownBytes:>8} <span color='{{ muted }}'>⇡</span>{bandwidthUpBytes:>8}",
    "format-ethernet": "<span color='{{ muted }}'>⇣</span>{bandwidthDownBytes:>8} <span color='{{ muted }}'>⇡</span>{bandwidthUpBytes:>8}"
  },
  "clock": {
    "calendar": {
      "format": {
        "months": "<span color='{{ primary }}'><b>{}</b></span>",
        "weeks": "<span color='{{ dim }}'>{}</span>",
        "weekdays": "<span color='{{ muted }}'>{}</span>",
        "days": "<span color='{{ soft }}'>{}</span>",
        "today": "<span background='{{ primary }}' color='{{ void }}'><b>{}</b></span>"
      }
    }
  }
}
