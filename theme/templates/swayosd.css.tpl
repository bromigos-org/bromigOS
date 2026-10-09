/* swayosd (the on-screen display for volume, brightness and mute): theme "{{ theme }}" ({{ meta.name }}),
   written by `bromigos theme set`. Don't edit; swayosd-server --style reads it (hooks/theme-set.d/osd). */
window#osd {
    background-color: {{ panel }};
    border: 1px solid {{ dim }};
    border-radius: 0;
    padding: 10px 18px;
    color: {{ soft }};
    font-family: "Geist Mono";
    font-size: 13px;
}
#container {
    margin: 0;
}
image, label {
    color: {{ soft }};
}
label {
    letter-spacing: 1px;
}
progressbar {
    min-height: 6px;
    border-radius: 0;
    background-color: transparent;
    border: none;
}
trough {
    min-height: 6px;
    border-radius: 0;
    background-color: {{ selection }};
    border: none;
}
progress {
    min-height: 6px;
    border-radius: 0;
    background-color: {{ primary }};
    border: none;
}
