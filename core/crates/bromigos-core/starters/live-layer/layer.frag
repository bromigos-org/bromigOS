#version 330 core
// __TITLE__: a shader layer over the background (made by `bromigos ext new live-layer`).
// Drawn after the background, behind every window, at its frame rate; its GPU time is
// measured, and over budget_ms (layer.json) it is switched off until the file changes.
in vec2 v_uv;            // 0..1, origin bottom-left
out vec4 frag;           // premultiplied; with blend "add" only rgb counts
uniform vec2  u_res;     // pixels
uniform float u_time;    // seconds
uniform float u_opacity; // layer.json's opacity
uniform vec4  u_load;    // cpu, gpu, memory, vram (0..1, real readings)
uniform vec4  u_net;     // rx, tx (log-scaled 0..1), their recent peaks
uniform float u_health;  // 0 all green, 1 hot or stale, 2 something down
uniform vec4  u_rect;    // x, y, w, h in pixels

void main() {
    // a band that sweeps up the screen, faster with the CPU's load
    float speed = 0.04 + 0.25 * u_load.x;
    float y = fract(u_time * speed);
    float d = abs(v_uv.y - y);
    float band = exp(-d * d * 9000.0) + 0.25 * exp(-d * 60.0);
    // teal when all is well, amber when something's hot, red when something's down
    vec3 ok = vec3(0.25, 0.85, 0.80);
    vec3 hot = vec3(1.0, 0.75, 0.25);
    vec3 down = vec3(1.0, 0.30, 0.35);
    vec3 c = mix(ok, hot, clamp(u_health, 0.0, 1.0));
    c = mix(c, down, clamp(u_health - 1.0, 0.0, 1.0));
    frag = vec4(c * band * u_opacity, 1.0);
}
