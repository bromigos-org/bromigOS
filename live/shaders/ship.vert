#version 330 core
// Starship wireframe: one VBO of edge quads (6 vertices per edge), drawn instanced
// (one instance per ship) in a single call. Feeds line.frag.
layout(location = 0) in vec3 a_p0;
layout(location = 1) in vec3 a_p1;
layout(location = 2) in vec3 a_cp;     // corner along, corner side, part
#include common
#include ship
uniform float u_width;
out vec4 v_col;
out float v_dist;
out float v_hw;
out float v_along;
out float v_dash;
out vec2 v_px;
flat out vec4 v_clip;
void main() {
    int i = gl_InstanceID;
    vec3 s0 = project(ship_world(a_p0, i), 2.0);
    vec3 s1 = project(ship_world(a_p1, i), 2.0);
    vec2 d = s1.xy - s0.xy;
    float len = max(length(d), 1e-3);
    d /= len;
    vec2 n = vec2(-d.y, d.x);
    int part = int(a_cp.z + 0.5);
    float hw = u_width * (part >= 3 ? 1.6 : 1.0) * 0.5;
    float pad = hw + 1.25;
    vec2 p = mix(s0.xy - d * pad, s1.xy + d * pad, a_cp.x) + n * pad * (a_cp.y * 2.0 - 1.0);
    gl_Position = to_clip(p);
    v_px = p;
    v_clip = clip_of(2.0);
    v_dist = pad * (a_cp.y * 2.0 - 1.0);
    v_hw = hw;
    v_along = 0.0;
    v_dash = 0.0;
    vec4 c = ship_colour(part, i);
    float z = mix(s0.z, s1.z, a_cp.x);
    v_col = vec4(c.rgb, c.a * u_so[i].w * depth_fade(z, 2.0) * u_fade);
}
