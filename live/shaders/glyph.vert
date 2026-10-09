#version 330 core
layout(location = 0) in vec4 a_anchor;   // xyz, space
layout(location = 1) in vec4 a_box;      // off x, off y, w, h (px)
layout(location = 2) in vec4 a_uv;
layout(location = 3) in vec4 a_col;
layout(location = 4) in vec4 a_ex;       // reveal t0, flash, -, -
#include common
out vec2 v_uv;
out vec4 v_col;
out vec2 v_px;
flat out vec4 v_clip;
void main() {
    vec3 s = project(a_anchor.xyz, a_anchor.w);
    vec2 base = floor(s.xy + a_box.xy + 0.5);
    vec2 c = corner(gl_VertexID);
    gl_Position = to_clip(base + c * a_box.zw);
    v_px = base + c * a_box.zw;
    v_clip = clip_of(a_anchor.w);
    v_uv = mix(a_uv.xy, a_uv.zw, c);
    vec4 col = a_col;
    col.a *= u_fade * (a_anchor.w > 0.5 ? depth_fade(s.z, a_anchor.w) * 0.5 + 0.5 : 1.0);
    if (a_ex.x > 0.0) {
        float dt = u_time - a_ex.x;
        if (dt < 0.0) col.a = 0.0;
        else col.rgb = mix(col.rgb, vec3(0.92, 1.0, 0.88), a_ex.y * exp(-dt * 14.0));
    }
    v_col = col;
}
