{#- One block of foreground roles, shared by most colour sets. -#}
{%- macro fg(normal, inactive) -%}
ForegroundNormal={{ normal | rgb }}
ForegroundInactive={{ inactive | rgb }}
ForegroundActive={{ primary | rgb }}
ForegroundLink={{ primary | rgb }}
ForegroundVisited={{ dim | rgb }}
ForegroundNegative={{ danger | rgb }}
ForegroundNeutral={{ warn | rgb }}
ForegroundPositive={{ primary | rgb }}
DecorationFocus={{ primary | rgb }}
DecorationHover={{ dim | rgb }}
{%- endmacro -%}
# KDE/Qt colour scheme (Dolphin, Kate, Okular, file dialogs): theme "{{ theme }}"
# ({{ meta.name }}), written by `bromigos theme set`. Don't edit. The scheme keeps the
# name Bromigos whichever theme is active; apply it with
# `plasma-apply-colorscheme Bromigos` (writes kdeglobals).

[General]
ColorScheme=Bromigos
Name=Bromigos
shadeSortColumn=true

[KDE]
contrast=6

[ColorEffects:Disabled]
Color={{ panel | rgb }}
ColorAmount=0.55
ColorEffect=3
ContrastAmount=0.55
ContrastEffect=1
IntensityAmount=0.1
IntensityEffect=2

[ColorEffects:Inactive]
ChangeSelectionColor=true
Color={{ panel | rgb }}
ColorAmount=0
ColorEffect=0
ContrastAmount=0
ContrastEffect=0
Enable=false
IntensityAmount=0
IntensityEffect=0

[Colors:View]
BackgroundNormal={{ qt.view | rgb }}
BackgroundAlternate={{ qt.view_alt | rgb }}
{{ fg(soft, muted) }}

[Colors:Window]
BackgroundNormal={{ panel | rgb }}
BackgroundAlternate={{ qt.window_alt | rgb }}
{{ fg(soft, muted) }}

[Colors:Header]
BackgroundNormal={{ qt.header | rgb }}
BackgroundAlternate={{ panel | rgb }}
{{ fg(soft, muted) }}

[Colors:Header][Inactive]
BackgroundNormal={{ qt.view | rgb }}
BackgroundAlternate={{ qt.header | rgb }}
{{ fg(muted, faint) }}

[Colors:Button]
BackgroundNormal={{ qt.button | rgb }}
BackgroundAlternate={{ selection | rgb }}
{{ fg(soft, muted) }}

[Colors:Selection]
BackgroundNormal={{ dim | rgb }}
BackgroundAlternate={{ selection | rgb }}
ForegroundNormal={{ void | rgb }}
ForegroundInactive={{ panel | rgb }}
ForegroundActive={{ void | rgb }}
ForegroundLink={{ void | rgb }}
ForegroundVisited={{ panel | rgb }}
ForegroundNegative={{ qt.negative_on_selection | rgb }}
ForegroundNeutral={{ qt.neutral_on_selection | rgb }}
ForegroundPositive={{ void | rgb }}
DecorationFocus={{ primary | rgb }}
DecorationHover={{ primary | rgb }}

[Colors:Tooltip]
BackgroundNormal={{ void | rgb }}
BackgroundAlternate={{ panel | rgb }}
{{ fg(soft, muted) }}

[Colors:Complementary]
BackgroundNormal={{ void | rgb }}
BackgroundAlternate={{ qt.header | rgb }}
{{ fg(soft, muted) }}

[WM]
activeBackground={{ panel | rgb }}
activeBlend={{ primary | rgb }}
activeForeground={{ primary | rgb }}
inactiveBackground={{ qt.view | rgb }}
inactiveBlend={{ muted | rgb }}
inactiveForeground={{ muted | rgb }}
