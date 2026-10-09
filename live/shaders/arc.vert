#version 330 core
layout(location = 0) in vec4 a_c;     // centre xyz, space
layout(location = 1) in vec4 a_e;     // travel end xyz, speed (packets) | plate half extents
layout(location = 2) in vec4 a_r;     // r0, r1, a0, a1
layout(location = 3) in vec4 a_s;     // segments, gap, spin, phase
layout(location = 4) in vec4 a_col;
layout(location = 5) in vec4 a_ex;    // reveal t0, kind, part, soft
#include common
out vec2 v_p;
out vec4 v_r;
out vec4 v_s;
out vec4 v_col;
out vec4 v_ex;
out vec2 v_half;
out vec2 v_px;
flat out vec4 v_clip;
void main() {
    int kind = int(a_ex.y + 0.5);
    vec2 c = corner(gl_VertexID);
    vec4 col = a_col;
    if (kind == 3) {                     // rectangular plate
        vec2 h = a_e.xy + 1.0;
        vec2 p = a_c.xy + (c * 2.0 - 1.0) * h;
        gl_Position = to_clip(p);
        v_px = p;
        v_clip = vec4(0.0);
        v_p = (c * 2.0 - 1.0) * h;
        v_half = a_e.xy;
        v_col = col * vec4(1, 1, 1, u_fade);
        v_ex = a_ex; v_r = a_r; v_s = a_s;
        return;
    }
    vec3 pos = a_c.xyz;
    if (a_e.w > 0.0) {                   // packet: travels centre -> end
        float f = fract(u_time * a_e.w + a_s.w);
        pos = mix(a_c.xyz, a_e.xyz, f);
        col.a *= smoothstep(0.0, 0.12, f) * smoothstep(1.0, 0.85, f);
    }
    vec3 s = project(pos, a_c.w);
    float R = a_r.y + 2.0 + (kind == 2 ? a_r.y : 0.0);
    vec2 p = s.xy + (c * 2.0 - 1.0) * R;
    gl_Position = to_clip(p);
    v_px = p;
    v_clip = clip_of(a_c.w);
    v_p = (c * 2.0 - 1.0) * R;
    v_half = vec2(R);
    col.a *= depth_fade(s.z, a_c.w) * u_fade;
    int part = int(a_ex.z + 0.5);
    if (a_ex.z >= 0.0 && part < 32) {
        vec4 pp = u_part[part];
        col.rgb = heat(col.rgb, pp.y);
        col.a *= pp.x;
    }
    if (a_ex.x > 0.0 && u_time < a_ex.x) col.a = 0.0;
    v_col = col; v_r = a_r; v_s = a_s; v_ex = a_ex;
}
