#version 330 core
layout(location = 0) in vec4 a_p0;    // xyz, space
layout(location = 1) in vec4 a_p1;    // xyz, width
layout(location = 2) in vec4 a_col;
layout(location = 3) in vec4 a_ex;    // part, reveal t0, dash px, glow
layout(location = 4) in vec4 a_ex2;   // space of p1
#include common
out vec4 v_col;
out float v_dist;
out float v_hw;
out float v_along;
out float v_dash;
out vec2 v_px;
flat out vec4 v_clip;
void main() {
    vec3 s0 = project(a_p0.xyz, a_p0.w);
    vec3 s1 = project(a_p1.xyz, a_ex2.x);
    float r = reveal(a_ex.y, 0.45);
    s1.xy = mix(s0.xy, s1.xy, r);
    vec2 d = s1.xy - s0.xy;
    float len = max(length(d), 1e-3);
    d /= len;
    vec2 n = vec2(-d.y, d.x);
    float hw = a_p1.w * 0.5;
    float pad = hw + 1.25;
    vec2 c = corner(gl_VertexID);
    vec2 p = mix(s0.xy - d * pad, s1.xy + d * pad, c.x) + n * pad * (c.y * 2.0 - 1.0);
    gl_Position = to_clip(p);
    v_px = p;
    v_clip = clip_of(a_p0.w);
    v_dist = pad * (c.y * 2.0 - 1.0);
    v_hw = hw;
    v_along = mix(-pad, len + pad, c.x);
    v_dash = a_ex.z;
    vec4 col = a_col;
    float z = mix(s0.z, s1.z, c.x);
    col.a *= depth_fade(z, a_p0.w) * u_fade;
    int part = int(a_ex.x + 0.5);
    if (a_ex.x >= 0.0 && part < 32) {
        vec4 pp = u_part[part];
        col.rgb = heat(col.rgb, pp.y);
        col.a *= pp.x;
        if (pp.z > 0.5) col.rgb = mix(col.rgb, vec3(0.9, 1.0, 0.85), 0.35 + 0.15 * sin(u_time * 6.0));
    }
    col.a *= (a_ex.y > 0.0 && u_time < a_ex.y) ? 0.0 : 1.0;
    col.rgb *= a_ex.w;
    v_col = col;
}
